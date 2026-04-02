import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'
import { HAStatusPanel } from '@/components/ha/HAStatusPanel'

interface GlobalAdminData {
  platform_mrr?: number
  active_orgs?: number
  total_orgs?: number
  churn_rate?: number
  error_counts?: ErrorCounts
  integration_health?: IntegrationStatus[]
  billing_issues?: BillingIssue[]
  interval_breakdown?: MrrIntervalBreakdown[]
}

interface MrrIntervalBreakdown {
  interval: string
  org_count: number
  mrr_nzd: number
}

interface ErrorCounts {
  info: number
  warning: number
  error: number
  critical: number
}

interface IntegrationStatus {
  name: string
  status: 'healthy' | 'degraded' | 'down' | 'not_configured'
  last_checked: string | null
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
  token_last_refresh?: string | null
  token_expires_at?: string | null
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
  not_configured: 'warning',
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
          safeFetch<{ total_mrr_nzd?: number; mrr?: number; interval_breakdown?: MrrIntervalBreakdown[] }>('/admin/reports/mrr', {}),
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
        interval_breakdown: mrrData?.interval_breakdown ?? [],
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

      {/* MRR Interval Breakdown */}
      {(data.interval_breakdown ?? []).length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-medium text-gray-900">MRR by Billing Interval</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(data.interval_breakdown ?? []).map((ib) => {
              const totalMrr = data.platform_mrr ?? 0
              const pct = totalMrr > 0 ? ((ib.mrr_nzd / totalMrr) * 100) : 0
              return (
                <div
                  key={ib.interval}
                  className="rounded-lg border border-gray-200 bg-white p-4"
                >
                  <p className="text-sm font-medium capitalize text-gray-500">{ib.interval}</p>
                  <p className="mt-1 text-lg font-semibold text-gray-900">
                    ${(ib.mrr_nzd ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}
                  </p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {ib.org_count} org{ib.org_count !== 1 ? 's' : ''} · {pct.toFixed(1)}%
                  </p>
                </div>
              )
            })}
          </div>
        </section>
      )}

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
                      : integration.status === 'not_configured'
                        ? 'Not configured'
                        : integration.status === 'healthy'
                          ? 'Configured'
                          : 'Not verified'}
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

      {/* HA Cluster Status */}
      <HAStatusPanel />

      {/* Branch Revenue by Organisation */}
      <OrgBranchRevenueSection />
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

function formatCountdown(expiresAt: string): string {
  const diff = new Date(expiresAt).getTime() - Date.now()
  if (diff <= 0) return 'expired'
  const h = Math.floor(diff / 3_600_000)
  const m = Math.floor((diff % 3_600_000) / 60_000)
  const s = Math.floor((diff % 60_000) / 1_000)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function TokenCountdown({ expiresAt }: { expiresAt: string }) {
  const [label, setLabel] = useState(() => formatCountdown(expiresAt))
  useEffect(() => {
    const id = setInterval(() => setLabel(formatCountdown(expiresAt)), 1000)
    return () => clearInterval(id)
  }, [expiresAt])
  const isExpired = new Date(expiresAt).getTime() <= Date.now()
  return (
    <span className={`font-medium ${isExpired ? 'text-red-500' : 'text-emerald-600'}`}>
      {label}
    </span>
  )
}

interface TokenRefreshEntry {
  timestamp: string
  reason: string
  trigger: string
  was_early: boolean
  token_remaining_secs: number | null
  success: boolean
}

function TokenRefreshLogModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [entries, setEntries] = useState<TokenRefreshEntry[]>([])
  const [loading, setLoading] = useState(false)

  const fetchLog = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ entries: TokenRefreshEntry[] }>(
        '/admin/dashboard/connexus-token-refresh-log',
      )
      setEntries(res.data.entries)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) fetchLog()
  }, [open, fetchLog])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Token refresh log"
    >
      <div
        className="w-full max-w-2xl max-h-[80vh] overflow-auto rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-5 py-3">
          <h3 className="text-lg font-semibold text-gray-900">Token Refresh Log</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4">
          {loading ? (
            <Spinner size="md" label="Loading refresh log" className="py-8" />
          ) : entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-500">
              No token refreshes recorded yet. Entries appear after the first refresh cycle.
            </p>
          ) : (
            <div className="space-y-3">
              {entries.map((entry, i) => (
                <div
                  key={`${entry.timestamp}-${i}`}
                  className={`rounded-lg border p-3 ${
                    entry.success
                      ? 'border-gray-200 bg-gray-50'
                      : 'border-red-200 bg-red-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900">{entry.reason}</p>
                    <Badge variant={entry.success ? 'success' : 'error'}>
                      {entry.success ? 'OK' : 'Failed'}
                    </Badge>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                    <span>{new Date(entry.timestamp).toLocaleString('en-NZ')}</span>
                    <span className="font-mono">{entry.trigger}</span>
                    {entry.was_early && (
                      <span className="text-amber-600">
                        ⚡ Early refresh ({entry.token_remaining_secs != null
                          ? `${Math.round(entry.token_remaining_secs)}s remaining`
                          : 'before expiry'})
                      </span>
                    )}
                    {!entry.was_early && entry.token_remaining_secs != null && (
                      <span className="text-red-500">
                        Token was expired ({Math.abs(Math.round(entry.token_remaining_secs))}s ago)
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function IntegrationCostCardView({ card }: { card: IntegrationCostCard }) {
  const [showRefreshLog, setShowRefreshLog] = useState(false)
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

      {/* Token refresh timing (Connexus SMS only) */}
      {(card.token_last_refresh || card.token_expires_at) && (
        <div className="mt-3 pt-3 border-t border-gray-100 space-y-1">
          {card.token_last_refresh && (
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Last Token Refresh</span>
              <span className="text-gray-600">
                {new Date(card.token_last_refresh).toLocaleString('en-NZ')}
              </span>
            </div>
          )}
          {card.token_expires_at && (
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Next Refresh In</span>
              <TokenCountdown expiresAt={card.token_expires_at} />
            </div>
          )}
          <button
            onClick={() => setShowRefreshLog(true)}
            className="mt-1.5 w-full rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
          >
            Refresh Reasons
          </button>
          <TokenRefreshLogModal
            open={showRefreshLog}
            onClose={() => setShowRefreshLog(false)}
          />
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


/* ── Org Branch Revenue Section ── */

interface OrgBranchRevenue {
  org_id: string
  org_name: string
  active_branch_count: number
  total_monthly_revenue: number
  per_branch_avg_revenue: number
}

interface OrgBranchRevenueResponse {
  orgs: OrgBranchRevenue[]
  platform_total_branches: number
  platform_total_revenue: number
  avg_branches_per_org: number
}

function OrgBranchRevenueSection() {
  const [data, setData] = useState<OrgBranchRevenueResponse | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const fetchData = async () => {
      try {
        const res = await apiClient.get<OrgBranchRevenueResponse>(
          '/admin/org-branch-revenue',
          { signal: controller.signal },
        )
        setData(res.data ?? null)
      } catch {
        // Silently fail — section just won't render
      }
    }
    fetchData()
    return () => controller.abort()
  }, [])

  if (!data || (data.orgs ?? []).length === 0) return null

  const fmt = (v: number) =>
    `$${(v ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  return (
    <section>
      <h2 className="mb-3 text-lg font-medium text-gray-900">Branch Revenue by Organisation</h2>

      {/* Platform summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Total Active Branches</p>
          <p className="text-xl font-semibold text-gray-900">{data.platform_total_branches ?? 0}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Total Branch Revenue</p>
          <p className="text-xl font-semibold text-gray-900">{fmt(data.platform_total_revenue ?? 0)}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Avg Branches / Org</p>
          <p className="text-xl font-semibold text-gray-900">{(data.avg_branches_per_org ?? 0).toFixed(1)}</p>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200" role="grid">
          <caption className="sr-only">Organisation branch revenue</caption>
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Organisation</th>
              <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Active Branches</th>
              <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Monthly Revenue</th>
              <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Per-Branch Avg</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white">
            {(data.orgs ?? []).map((org) => (
              <tr key={org.org_id} className="hover:bg-gray-50">
                <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{org.org_name ?? '—'}</td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{org.active_branch_count ?? 0}</td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-900">{fmt(org.total_monthly_revenue ?? 0)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{fmt(org.per_branch_avg_revenue ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
