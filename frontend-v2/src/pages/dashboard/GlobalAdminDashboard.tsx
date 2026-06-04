import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '@/api/client'
import { Badge, Spinner, AlertBanner, DataTable, cx, type Column } from '@/components/ui'
import { HAStatusPanel } from '@/components/ha/HAStatusPanel'

/* ============================================================
   GlobalAdminDashboard (Task 17) — the platform/global-admin dashboard.
   ------------------------------------------------------------
   Logic source: frontend/src/pages/dashboard/GlobalAdminDashboard.tsx.
   ALL data logic is copied VERBATIM (FR-1 / FR-2c):
     • Primary metrics fetched in parallel with per-endpoint safeFetch
       fallbacks + a 60s polling interval + cancelled guard:
         GET /api/v2/admin/analytics/overview   (orgs / mrr / churn)
         GET /admin/reports/mrr                  (platform MRR + breakdown)
         GET /admin/errors/dashboard             (error counts by severity)
         GET /admin/integrations                 (integration health)
         GET /admin/reports/billing-issues       (billing issues table)
     • Integration costs fetched separately with the period filter +
       its own 60s poll:
         GET /admin/dashboard/integration-costs?period=…
     • The Connexus token countdown + refresh-log modal
         GET /admin/dashboard/connexus-token-refresh-log
     • The HA cluster panel (GET /ha/* — see HAStatusPanel) and the
       org-branch-revenue section (GET /admin/org-branch-revenue).
     • error-count aggregation (by_severity → {info,warning,error,critical})
       and the critical-error banner — unchanged.

   Design (FR-2): restyled onto the redesign tokens using the same patterns
   MainDashboard established — `.page` wrapper + `.page-head`, KPI cards
   (label / mono value / sub), Card sections with Card.Head, Badge pills,
   the ported DataTable, and `.mono` for every number / money / countdown.
   The original's `warning`/`error` Badge variants map onto the new union's
   `warn`/`danger` tones. Number formatting is hardened with `?? 0`
   (safe-api-consumption) without changing any behaviour for valid data.

   Routing: in the original frontend this same Dashboard dispatcher is
   mounted at BOTH /admin/dashboard (under AdminLayout) and /dashboard;
   for a global_admin session it resolves to this component. In
   frontend-v2 the global_admin lands at /admin/dashboard (GuestOnly
   redirect), so App.tsx wires this component there (replacing the
   placeholder) and the /dashboard dispatcher renders it too for parity.
   ============================================================ */

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
    render: (row) => <span className="mono">${Number(row.amount ?? 0).toFixed(2)}</span>,
  },
  {
    key: 'created_at',
    header: 'Date',
    sortable: true,
    render: (row) => (
      <span className="mono">{new Date(String(row.created_at)).toLocaleDateString('en-NZ')}</span>
    ),
  },
]

/** Original `warning`/`error` map onto the new Badge union's `warn`/`danger`. */
const integrationStatusVariant: Record<IntegrationStatus['status'], 'success' | 'warn' | 'danger'> = {
  healthy: 'success',
  degraded: 'warn',
  down: 'danger',
  not_configured: 'warn',
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
      const [analyticsOverview, mrrData, errorDashboard, integrations, billing] = await Promise.all([
        safeFetch<{ total_orgs?: number; active_orgs?: number; mrr?: number; churn_rate?: number }>(
          '/api/v2/admin/analytics/overview',
          {},
        ),
        safeFetch<{ total_mrr_nzd?: number; mrr?: number; interval_breakdown?: MrrIntervalBreakdown[] }>(
          '/admin/reports/mrr',
          {},
        ),
        safeFetch<{
          by_severity?: Array<{ label: string; count_1h?: number; count_24h?: number; count_7d?: number; count?: number }>
          total_24h?: number
        }>('/admin/errors/dashboard', {}),
        safeFetch<IntegrationStatus[]>('/admin/integrations', []).then((val) =>
          Array.isArray(val) ? val : [],
        ),
        safeFetch<BillingIssue[]>('/admin/reports/billing-issues', []).then((val) =>
          Array.isArray(val) ? val : [],
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
    return () => {
      cancelled = true
      clearInterval(interval)
    }
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
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [costPeriod])

  if (isLoading) return <Spinner size="lg" label="Loading admin dashboard" className="py-20" />
  if (!data) return null

  const errorCounts = data.error_counts || { info: 0, warning: 0, error: 0, critical: 0 }
  const totalErrors = errorCounts.info + errorCounts.warning + errorCounts.error + errorCounts.critical

  return (
    <div className="page space-y-6">
      <div className="page-head">
        <div>
          <div className="eyebrow">Platform</div>
          <h1>Platform Dashboard</h1>
        </div>
      </div>

      {errorCounts.critical > 0 && (
        <AlertBanner variant="error" title="Critical Errors">
          {errorCounts.critical} critical error
          {errorCounts.critical !== 1 ? 's' : ''} detected. Review the error log immediately.
        </AlertBanner>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 lg:grid-cols-4">
        {data.platform_mrr != null && (
          <KpiCard
            label="Platform MRR"
            value={(data.platform_mrr ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}
            money
          />
        )}
        {data.active_orgs != null && (
          <KpiCard
            label="Active Organisations"
            value={String(data.active_orgs)}
            subtitle={
              data.total_orgs && data.total_orgs > data.active_orgs ? `${data.total_orgs} total` : undefined
            }
          />
        )}
        <KpiCard
          label="Total Errors (24h)"
          value={String(totalErrors)}
          variant={totalErrors > 0 ? 'warning' : undefined}
        />
        <KpiCard
          label="Billing Issues"
          value={String(data.billing_issues?.length || 0)}
          variant={(data.billing_issues?.length || 0) > 0 ? 'error' : undefined}
        />
      </div>

      {/* MRR Interval Breakdown */}
      {(data.interval_breakdown ?? []).length > 0 && (
        <section>
          <h2 className="mb-3 text-[15px] font-semibold text-text">MRR by Billing Interval</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(data.interval_breakdown ?? []).map((ib) => {
              const totalMrr = data.platform_mrr ?? 0
              const pct = totalMrr > 0 ? (ib.mrr_nzd / totalMrr) * 100 : 0
              return (
                <div key={ib.interval} className="rounded-card border border-border bg-card p-4 shadow-card">
                  <p className="text-[12.5px] font-medium capitalize text-muted">{ib.interval}</p>
                  <p className="mono mt-1 text-[18px] font-semibold text-text">
                    <span className="text-muted-2">$</span>
                    {(ib.mrr_nzd ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}
                  </p>
                  <p className="mono mt-0.5 text-[11px] text-muted-2">
                    {ib.org_count} org{ib.org_count !== 1 ? 's' : ''} · {pct.toFixed(1)}%
                  </p>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {data.churn_rate != null && data.churn_rate > 0 && (
        <div className="rounded-ctl border border-warn-soft bg-warn-soft px-4 py-3 text-[13px] text-warn">
          30-day churn rate: <span className="font-semibold">{data.churn_rate}%</span>
        </div>
      )}

      {/* Error counts by severity */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-text">Errors by Severity</h2>
          <Link to="/admin/errors" className="text-[12.5px] font-medium text-accent hover:underline">
            View error log →
          </Link>
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
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-text">Integration Health</h2>
          <Link to="/admin/integrations" className="text-[12.5px] font-medium text-accent hover:underline">
            Manage integrations →
          </Link>
        </div>
        {!data.integration_health || data.integration_health.length === 0 ? (
          <p className="text-[13px] text-muted">No integrations configured</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {data.integration_health.map((integration) => (
              <div
                key={integration.name}
                className="flex items-center justify-between rounded-card border border-border bg-card p-4 shadow-card"
              >
                <div>
                  <p className="text-[13.5px] font-medium capitalize text-text">{integration.name}</p>
                  <p className="text-[11px] text-muted">
                    {integration.last_checked
                      ? `Checked ${new Date(integration.last_checked).toLocaleTimeString('en-NZ')}`
                      : integration.status === 'not_configured'
                        ? 'Not configured'
                        : integration.status === 'healthy'
                          ? 'Configured'
                          : 'Not verified'}
                  </p>
                </div>
                <Badge variant={integrationStatusVariant[integration.status]}>{integration.status}</Badge>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Billing issues */}
      <section>
        <h2 className="mb-3 text-[15px] font-semibold text-text">Billing Issues</h2>
        <DataTable
          columns={billingColumns}
          data={(data.billing_issues ?? []) as unknown as Row[]}
          keyField="id"
          caption="Organisations with billing issues"
        />
      </section>

      {/* Integration Costs */}
      {integrationCosts && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-text">Integration Costs &amp; Usage</h2>
            <div className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]">
              {(['daily', 'weekly', 'monthly'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setCostPeriod(p)}
                  className={cx(
                    'rounded-[7px] px-[13px] py-1.5 text-[12.5px] font-medium capitalize transition-colors',
                    costPeriod === p ? 'bg-accent-soft text-accent' : 'text-muted hover:text-text',
                  )}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 lg:grid-cols-4">
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

/* ── KPI card — label / big mono value / optional sub, tone-coloured value ── */

type KpiVariant = 'error' | 'warning'

const KPI_VALUE_TONE: Record<KpiVariant, string> = {
  error: 'text-danger',
  warning: 'text-warn',
}

function KpiCard({
  label,
  value,
  variant,
  subtitle,
  money,
}: {
  label: string
  value: string
  variant?: KpiVariant
  subtitle?: string
  money?: boolean
}) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <p className="text-[12.5px] font-medium text-muted">{label}</p>
      <p
        className={cx(
          'mono mt-1.5 text-[27px] font-semibold leading-none tracking-[-0.02em]',
          variant ? KPI_VALUE_TONE[variant] : 'text-text',
        )}
      >
        {money && <span className="text-[17px] text-muted-2">$</span>}
        {value}
      </p>
      {subtitle && <p className="mono mt-2.5 text-[12px] font-medium text-muted-2">{subtitle}</p>}
    </div>
  )
}

/* ── Severity card — tone-tinted soft surface ── */

const SEVERITY_TONE: Record<'error' | 'warning' | 'info', string> = {
  error: 'border-danger-soft bg-danger-soft text-danger',
  warning: 'border-warn-soft bg-warn-soft text-warn',
  info: 'border-accent-soft bg-accent-soft text-accent',
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
  return (
    <div className={cx('rounded-card border p-4', SEVERITY_TONE[variant])}>
      <p className="text-[12.5px] font-medium">{label}</p>
      <p className="mono mt-1 text-[20px] font-semibold">{count}</p>
    </div>
  )
}

/* ── Integration cost card status border tones ── */

const statusColors: Record<string, { border: string; badge: 'success' | 'warn' | 'danger' | 'neutral' }> = {
  healthy: { border: 'border-ok', badge: 'success' },
  degraded: { border: 'border-warn', badge: 'warn' },
  down: { border: 'border-danger', badge: 'danger' },
  not_configured: { border: 'border-border', badge: 'neutral' },
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
  return <span className={cx('mono font-medium', isExpired ? 'text-danger' : 'text-ok')}>{label}</span>
}

interface TokenRefreshEntry {
  timestamp: string
  reason: string
  trigger: string
  was_early: boolean
  token_remaining_secs: number | null
  success: boolean
}

function TokenRefreshLogModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [entries, setEntries] = useState<TokenRefreshEntry[]>([])
  const [loading, setLoading] = useState(false)

  const fetchLog = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ entries: TokenRefreshEntry[] }>(
        '/admin/dashboard/connexus-token-refresh-log',
      )
      setEntries(res.data?.entries ?? [])
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Token refresh log"
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-card border border-border bg-card shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-[17px]">
          <h3 className="text-[15px] font-semibold text-text">Token Refresh Log</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-muted-2 transition-colors hover:bg-canvas hover:text-text"
            aria-label="Close"
            type="button"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4">
          {loading ? (
            <Spinner size="md" label="Loading refresh log" className="py-8" />
          ) : entries.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-muted">
              No token refreshes recorded yet. Entries appear after the first refresh cycle.
            </p>
          ) : (
            <div className="space-y-3">
              {entries.map((entry, i) => (
                <div
                  key={`${entry.timestamp}-${i}`}
                  className={cx(
                    'rounded-ctl border p-3',
                    entry.success ? 'border-border bg-canvas' : 'border-danger-soft bg-danger-soft',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-[13.5px] font-medium text-text">{entry.reason}</p>
                    <Badge variant={entry.success ? 'success' : 'danger'}>
                      {entry.success ? 'OK' : 'Failed'}
                    </Badge>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                    <span>{new Date(entry.timestamp).toLocaleString('en-NZ')}</span>
                    <span className="mono">{entry.trigger}</span>
                    {entry.was_early && (
                      <span className="text-warn">
                        ⚡ Early refresh (
                        {entry.token_remaining_secs != null
                          ? `${Math.round(entry.token_remaining_secs)}s remaining`
                          : 'before expiry'}
                        )
                      </span>
                    )}
                    {!entry.was_early && entry.token_remaining_secs != null && (
                      <span className="text-danger">
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

function IntegrationCostCardView({ card }: { card: IntegrationCostCard | null | undefined }) {
  const [showRefreshLog, setShowRefreshLog] = useState(false)
  // Safe consumption: the integration-costs endpoint may omit a provider (or
  // return a partial object); render nothing for a missing card rather than
  // crashing on `card.status`.
  if (!card) return null
  const colors = statusColors[card.status] || statusColors.not_configured
  const fmt = (v: number | null | undefined) =>
    `$${(v ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const breakdown = card.breakdown || {}

  return (
    <div className={cx('rounded-card border bg-card p-4 shadow-card', colors.border)}>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[13.5px] font-semibold text-text">{card.name}</p>
        <Badge variant={colors.badge}>{card.status}</Badge>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-[13px]">
          <span className="text-muted">Cost</span>
          <span className="mono font-semibold text-text">{fmt(card.total_cost_nzd)}</span>
        </div>
        <div className="flex justify-between text-[13px]">
          <span className="text-muted">Usage</span>
          <span className="mono font-medium text-text">
            {(card.total_usage ?? 0).toLocaleString()} {card.usage_label}
          </span>
        </div>

        {card.balance != null && (
          <div className="flex justify-between text-[13px]">
            <span className="text-muted">Balance</span>
            <span className="mono font-medium text-accent">
              {fmt(card.balance)} {card.balance_currency || 'NZD'}
            </span>
          </div>
        )}
      </div>

      {/* Breakdown details */}
      {Object.keys(breakdown).length > 0 && (
        <div className="mt-3 space-y-1 border-t border-border pt-3">
          {Object.entries(breakdown).map(([key, value]) => (
            <div key={key} className="flex justify-between text-[11px]">
              <span className="capitalize text-muted-2">{key.replace(/_/g, ' ')}</span>
              <span className="mono text-muted">
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
        <div className="mt-3 space-y-1 border-t border-border pt-3">
          {card.token_last_refresh && (
            <div className="flex justify-between text-[11px]">
              <span className="text-muted-2">Last Token Refresh</span>
              <span className="text-muted">{new Date(card.token_last_refresh).toLocaleString('en-NZ')}</span>
            </div>
          )}
          {card.token_expires_at && (
            <div className="flex justify-between text-[11px]">
              <span className="text-muted-2">Next Refresh In</span>
              <TokenCountdown expiresAt={card.token_expires_at} />
            </div>
          )}
          <button
            type="button"
            onClick={() => setShowRefreshLog(true)}
            className="mt-1.5 w-full rounded-ctl border border-accent-soft bg-accent-soft px-2 py-1 text-[11px] font-medium text-accent transition-colors hover:brightness-95"
          >
            Refresh Reasons
          </button>
          <TokenRefreshLogModal open={showRefreshLog} onClose={() => setShowRefreshLog(false)} />
        </div>
      )}

      {card.last_checked && (
        <p className="mt-2 text-[11px] text-muted-2">
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
        const res = await apiClient.get<OrgBranchRevenueResponse>('/admin/org-branch-revenue', {
          signal: controller.signal,
        })
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
      <h2 className="mb-3 text-[15px] font-semibold text-text">Branch Revenue by Organisation</h2>

      {/* Platform summary */}
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <p className="text-[13px] text-muted">Total Active Branches</p>
          <p className="mono mt-1 text-[20px] font-semibold text-text">{data.platform_total_branches ?? 0}</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <p className="text-[13px] text-muted">Total Branch Revenue</p>
          <p className="mono mt-1 text-[20px] font-semibold text-text">{fmt(data.platform_total_revenue ?? 0)}</p>
        </div>
        <div className="rounded-card border border-border bg-card p-4 shadow-card">
          <p className="text-[13px] text-muted">Avg Branches / Org</p>
          <p className="mono mt-1 text-[20px] font-semibold text-text">{(data.avg_branches_per_org ?? 0).toFixed(1)}</p>
        </div>
      </div>

      <div className="overflow-x-auto rounded-card border border-border bg-card shadow-card">
        <table className="w-full border-collapse" role="grid">
          <caption className="sr-only">Organisation branch revenue</caption>
          <thead>
            <tr>
              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Organisation
              </th>
              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Active Branches
              </th>
              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Monthly Revenue
              </th>
              <th scope="col" className="mono border-b border-border px-5 py-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                Per-Branch Avg
              </th>
            </tr>
          </thead>
          <tbody>
            {(data.orgs ?? []).map((org) => (
              <tr key={org.org_id} className="border-b border-border transition-colors last:border-b-0 hover:bg-canvas">
                <td className="px-5 py-3 text-[13.5px] font-medium text-text">{org.org_name ?? '—'}</td>
                <td className="mono px-5 py-3 text-right text-[13.5px] text-muted">{org.active_branch_count ?? 0}</td>
                <td className="mono px-5 py-3 text-right text-[13.5px] text-text">{fmt(org.total_monthly_revenue ?? 0)}</td>
                <td className="mono px-5 py-3 text-right text-[13.5px] text-muted">{fmt(org.per_branch_avg_revenue ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default GlobalAdminDashboard
