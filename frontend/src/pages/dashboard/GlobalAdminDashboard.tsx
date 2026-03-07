import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { DataTable, type Column } from '@/components/ui/DataTable'

interface GlobalAdminData {
  platform_mrr: number
  active_orgs: number
  error_counts: ErrorCounts
  integration_health: IntegrationStatus[]
  billing_issues: BillingIssue[]
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

type Row = Record<string, unknown>

const billingColumns: Column<Row>[] = [
  { key: 'org_name', header: 'Organisation', sortable: true },
  { key: 'issue_type', header: 'Issue', sortable: true },
  {
    key: 'amount',
    header: 'Amount',
    sortable: true,
    render: (row) => `$${Number(row.amount).toFixed(2)}`,
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

export function GlobalAdminDashboard() {
  const [data, setData] = useState<GlobalAdminData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function fetchDashboard() {
      try {
        const [mrrRes, orgsRes, errorsRes, integrationsRes, billingRes] =
          await Promise.all([
            apiClient.get<{ mrr: number }>('/admin/reports/mrr'),
            apiClient.get<{ total_active: number }>('/admin/reports/organisations'),
            apiClient.get<ErrorCounts>('/admin/errors', {
              params: { summary: true },
            }),
            apiClient.get<IntegrationStatus[]>('/admin/integrations'),
            apiClient.get<BillingIssue[]>('/admin/reports/billing-issues'),
          ])
        if (!cancelled) {
          setData({
            platform_mrr: mrrRes.data.mrr,
            active_orgs: orgsRes.data.total_active,
            error_counts: errorsRes.data,
            integration_health: integrationsRes.data,
            billing_issues: billingRes.data,
          })
        }
      } catch {
        if (!cancelled) setError('Failed to load admin dashboard data')
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    fetchDashboard()
    return () => {
      cancelled = true
    }
  }, [])

  if (isLoading) return <Spinner size="lg" label="Loading admin dashboard" className="py-20" />
  if (error) return <AlertBanner variant="error">{error}</AlertBanner>
  if (!data) return null

  const totalErrors = data.error_counts.info + data.error_counts.warning + data.error_counts.error + data.error_counts.critical

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900">Platform Dashboard</h1>

      {data.error_counts.critical > 0 && (
        <AlertBanner variant="error" title="Critical Errors">
          {data.error_counts.critical} critical error
          {data.error_counts.critical !== 1 ? 's' : ''} detected. Review the error log immediately.
        </AlertBanner>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Platform MRR"
          value={`$${data.platform_mrr.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`}
        />
        <KpiCard label="Active Organisations" value={data.active_orgs} />
        <KpiCard label="Total Errors (Recent)" value={totalErrors} variant={totalErrors > 0 ? 'warning' : undefined} />
        <KpiCard label="Billing Issues" value={data.billing_issues.length} variant={data.billing_issues.length > 0 ? 'error' : undefined} />
      </div>

      {/* Error counts by severity */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-gray-900">Errors by Severity</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SeverityCard label="Critical" count={data.error_counts.critical} variant="error" />
          <SeverityCard label="Error" count={data.error_counts.error} variant="error" />
          <SeverityCard label="Warning" count={data.error_counts.warning} variant="warning" />
          <SeverityCard label="Info" count={data.error_counts.info} variant="info" />
        </div>
      </section>

      {/* Integration health */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-gray-900">Integration Health</h2>
        {data.integration_health.length === 0 ? (
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
                    Checked {new Date(integration.last_checked).toLocaleTimeString('en-NZ')}
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
    </div>
  )
}

function KpiCard({
  label,
  value,
  variant,
}: {
  label: string
  value: number | string
  variant?: 'error' | 'warning'
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
