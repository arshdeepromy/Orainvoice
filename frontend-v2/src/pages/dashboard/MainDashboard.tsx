import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useTenant } from '@/contexts/TenantContext'
import { useBranch } from '@/contexts/BranchContext'
import { useModules } from '@/contexts/ModuleContext'
import { Card, Badge, Spinner, AlertBanner, statusToBadgeVariant, cx } from '@/components/ui'

/* ============================================================
   MainDashboard — the org-user dashboard (Task 16).
   ------------------------------------------------------------
   Design source: OraInvoice_Handoff/app/Dashboard.html
     • page-head greeting + range segmented control
     • KPI row (4 cards: Revenue MTD / Outstanding / Overdue / Jobs)
     • grid-2: left stack (Revenue area chart + Recent invoices table),
       right stack (Activity feed + Upcoming bookings)

   Logic source: the original /dashboard renders a role-dispatcher
   (frontend/src/pages/dashboard/Dashboard.tsx) that picks one of
   SalespersonDashboard / OrgAdminDashboard / GlobalAdminDashboard.
   None of those variants matches the prototype's single rich layout —
   the prototype IS the redesigned org dashboard that the role variants
   (Task 17) will be restyled into. So this page reuses the exact API
   calls + data mapping those variants make, composed into the prototype
   layout:
     • Revenue (MTD)  → GET /reports/revenue?preset=…    (OrgAdminDashboard)
     • Outstanding    → GET /reports/outstanding          (OrgAdminDashboard)
     • Overdue        → derived from /reports/outstanding  (OrgAdminDashboard:
                        invoices.filter(days_overdue > 0))
     • Jobs in prog.  → GET /job-cards?active_only=true    (SalespersonDashboard
                        active job cards; gated by the `jobs` module)
     • Recent invoices→ GET /invoices?limit=6              (SalespersonDashboard)
     • Revenue chart  → GET /dashboard/widgets/cash-flow   (CashFlowChartWidget)
     • Upcoming books → GET /bookings?view=week            (gated by `bookings`)

   Design-on-the-fly (FR-2b), documented inline at each call site:
     • The 7D/30D/QTR/YR range control is wired to the revenue preset +
       chart period (the prototype's control is cosmetic; here it drives
       real refetches).
     • The Activity feed has no backend endpoint anywhere in the app, so
       it is SYNTHESISED from the already-fetched recent invoices (status →
       event). No data is fabricated — every entry is a real invoice.
     • BookingSearchResult carries no price, so the prototype's per-booking
       amount is replaced with the real scheduled time.

   Safe API consumption: every list is `res.data?.x ?? []`, every number is
   `?? 0` (money coerced via Number() because the backend serialises Decimal
   as a string), one AbortController per effect, typed generics, no `as any`.
   ============================================================ */

/* ── Backend response shapes (fields mirror the Pydantic schemas) ── */

interface RevenueSummary {
  // Decimal fields serialise as strings over JSON — coerce with Number().
  total_inclusive: number | string
  total_revenue: number | string
  invoice_count: number
}

interface OutstandingInvoiceRow {
  invoice_id: string
  invoice_number: string | null
  customer_name: string
  balance_due: number | string
  days_overdue: number
}

interface OutstandingData {
  total_outstanding: number | string
  count: number
  invoices: OutstandingInvoiceRow[]
}

interface InvoiceRow {
  id: string
  invoice_number: string | null
  customer_name: string | null
  total: number | string
  status: string
  issue_date: string | null
}

interface BookingRow {
  id: string
  customer_name: string | null
  vehicle_rego: string | null
  service_type: string | null
  scheduled_at: string | null
  start_time: string | null
  status: string
}

interface CashFlowPoint {
  month: string
  month_label: string
  revenue: number
  expenses: number
}

/* ── Range control → revenue preset + chart period mapping ── */

type Range = '7D' | '30D' | 'QTR' | 'YR'

const RANGE_CONFIG: Record<
  Range,
  { preset: 'week' | 'month' | 'quarter' | 'year'; period: 'daily' | 'weekly' | 'monthly'; days: number }
> = {
  '7D': { preset: 'week', period: 'daily', days: 14 },
  '30D': { preset: 'month', period: 'weekly', days: 90 },
  QTR: { preset: 'quarter', period: 'monthly', days: 180 },
  YR: { preset: 'year', period: 'monthly', days: 365 },
}

const RANGE_ORDER: Range[] = ['7D', '30D', 'QTR', 'YR']

/* ── Formatting helpers ── */

/** Money → "48,250.00" (no symbol). Decimal-as-string safe. Matches the
 *  source dashboards' `Number(x).toLocaleString('en-NZ', …)` pattern. */
function formatMoney(v: number | string | null | undefined): string {
  return Number(v ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** Whole-dollar money for chart axis/tooltip. */
function formatMoney0(v: number | null | undefined): string {
  return `$${Number(v ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

/** Relative "12m / 5h / 2d" label for the synthesised activity feed. */
function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diffMs = Date.now() - then
  if (diffMs < 0) return 'now'
  const mins = Math.floor(diffMs / 60_000)
  if (mins < 60) return `${Math.max(mins, 1)}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}

/** Time-of-day greeting from the local clock. */
function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

/** Eyebrow date — e.g. "Tuesday · 12 Nov 2025" (matches the prototype). */
function todayLabel(): string {
  const now = new Date()
  const weekday = now.toLocaleDateString('en-NZ', { weekday: 'long' })
  const rest = now.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  return `${weekday} · ${rest}`
}

/* ── Inline stroke icons (no icon dep — matches the widget convention) ── */

type IconProps = { className?: string }

function DollarIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M12 1v22M17 5H9.5a3.5 3.5 0 100 7h5a3.5 3.5 0 110 7H6" />
    </svg>
  )
}
function DocIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h7l5 5v11a2 2 0 01-2 2z" />
    </svg>
  )
}
function AlertIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />
    </svg>
  )
}
function WrenchIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.4-9.4a2 2 0 112.8 2.8L11.8 15H9v-2.8l8.6-8.6z" />
    </svg>
  )
}
function BankIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
    </svg>
  )
}

/* ── KPI tones (icon chip background/foreground from ds.css .ico.*) ── */

type KpiTone = 'green' | 'blue' | 'red' | 'amber'

const KPI_ICON_TONE: Record<KpiTone, string> = {
  green: 'bg-ok-soft text-ok',
  blue: 'bg-accent-soft text-accent',
  red: 'bg-danger-soft text-danger',
  amber: 'bg-warn-soft text-warn',
}

interface KpiCardProps {
  label: string
  /** Big value. Money values are prefixed with a muted "$" (prototype `.c`). */
  value: string
  money?: boolean
  sub?: string
  icon: React.ComponentType<IconProps>
  tone: KpiTone
}

/** Single KPI card — mirrors the prototype `.kpi` (label/icon, mono value, sub). */
function KpiCard({ label, value, money, sub, icon: Icon, tone }: KpiCardProps) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <div className="mb-3.5 flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-muted">{label}</span>
        <span className={cx('grid h-8 w-8 place-items-center rounded-[9px]', KPI_ICON_TONE[tone])}>
          <Icon className="h-[17px] w-[17px]" />
        </span>
      </div>
      <div className="mono text-[27px] font-semibold leading-none tracking-[-0.02em]">
        {money && <span className="text-[17px] text-muted-2">$</span>}
        {value}
      </div>
      {sub && <p className="mono mt-2.5 text-[12px] font-medium text-muted-2">{sub}</p>}
    </div>
  )
}

/* ── Activity feed item (synthesised from a recent invoice) ── */

interface ActivityEntry {
  id: string
  tone: KpiTone
  icon: React.ComponentType<IconProps>
  title: string
  sub: string
  time: string
}

/** Map an invoice into a real activity entry (FR-2b: no activity endpoint
 *  exists, so the feed is derived from already-fetched invoices). */
function invoiceToActivity(inv: InvoiceRow): ActivityEntry {
  const status = (inv.status ?? '').toLowerCase()
  let tone: KpiTone = 'blue'
  let icon: React.ComponentType<IconProps> = DocIcon
  let title = 'Invoice updated'
  if (status === 'paid') {
    tone = 'green'
    icon = BankIcon
    title = 'Payment received'
  } else if (status === 'overdue') {
    tone = 'red'
    icon = AlertIcon
    title = 'Invoice overdue'
  } else if (status === 'sent' || status === 'issued') {
    tone = 'blue'
    icon = DocIcon
    title = 'Invoice sent'
  } else if (status === 'draft') {
    tone = 'amber'
    icon = DocIcon
    title = 'Invoice drafted'
  }
  const customer = inv.customer_name ?? 'Unknown customer'
  const number = inv.invoice_number ?? 'DRAFT'
  return {
    id: inv.id,
    tone,
    icon,
    title,
    sub: `${customer} · ${number}`,
    time: relativeTime(inv.issue_date),
  }
}

const ACTIVITY_DOT_TONE: Record<KpiTone, string> = KPI_ICON_TONE

/* ── Chart tooltip (design-on-the-fly, ds.css surface language) ── */

/** Minimal shape of the props recharts passes to a custom tooltip content
 *  function. Typed locally (rather than importing recharts' internal
 *  TooltipContentProps) so the component stays decoupled from recharts'
 *  v3 type-export layout. */
interface ChartTooltipProps {
  active?: boolean
  label?: string | number
  payload?: Array<{ value?: number | string }>
}

function ChartTooltip({ active, payload, label }: ChartTooltipProps) {
  if (!active || !(payload ?? []).length) return null
  const value = payload?.[0]?.value
  const numeric = typeof value === 'number' ? value : Number(value ?? 0)
  return (
    <div className="rounded-ctl border border-border bg-card px-3 py-2 shadow-pop">
      <p className="text-[11px] font-medium text-muted">{label}</p>
      <p className="mono text-[13px] font-semibold text-text">{formatMoney0(numeric)}</p>
    </div>
  )
}

/* ── Main page ── */

export function MainDashboard() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { settings } = useTenant()
  const { selectedBranchId } = useBranch()
  const { isEnabled } = useModules()

  const jobsEnabled = isEnabled('jobs')
  const bookingsEnabled = isEnabled('bookings')

  const [range, setRange] = useState<Range>('30D')

  const [revenue, setRevenue] = useState<RevenueSummary | null>(null)
  const [outstanding, setOutstanding] = useState<OutstandingData | null>(null)
  const [jobsInProgress, setJobsInProgress] = useState<number>(0)
  const [recentInvoices, setRecentInvoices] = useState<InvoiceRow[]>([])
  const [bookings, setBookings] = useState<BookingRow[]>([])
  const [chartSeries, setChartSeries] = useState<CashFlowPoint[]>([])

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    async function fetchDashboard() {
      setIsLoading(true)
      setError(null)

      const cfg = RANGE_CONFIG[range]
      // Branch scoping mirrors OrgAdminDashboard: pass branch_id when a
      // specific branch is selected (the interceptor also sets X-Branch-Id).
      const branchParams: Record<string, string> = {}
      if (selectedBranchId) branchParams.branch_id = selectedBranchId

      // Primary KPI sources — revenue + outstanding. If BOTH reject the page
      // shows an error banner (matches OrgAdminDashboard's single-error model);
      // every other section degrades to its own empty state.
      const [
        revenueRes,
        outstandingRes,
        jobsRes,
        invoicesRes,
        bookingsRes,
        cashFlowRes,
      ] = await Promise.allSettled([
        apiClient.get<RevenueSummary>('/reports/revenue', {
          params: { preset: cfg.preset, ...branchParams },
          signal: controller.signal,
        }),
        apiClient.get<OutstandingData>('/reports/outstanding', {
          params: branchParams,
          signal: controller.signal,
        }),
        // Jobs in progress — only when the jobs module is enabled (module gate).
        jobsEnabled
          ? apiClient.get<{ job_cards: unknown[]; total: number }>('/job-cards', {
              params: { active_only: true, limit: 1 },
              signal: controller.signal,
            })
          : Promise.resolve(null),
        apiClient.get<{ invoices: InvoiceRow[]; total: number }>('/invoices', {
          params: { limit: 6, offset: 0, ...branchParams },
          signal: controller.signal,
        }),
        // Upcoming bookings — only when the bookings module is enabled.
        bookingsEnabled
          ? apiClient.get<{ bookings: BookingRow[]; total: number }>('/bookings', {
              params: { view: 'week' },
              signal: controller.signal,
            })
          : Promise.resolve(null),
        apiClient.get<{ items: CashFlowPoint[]; total: number }>('/dashboard/widgets/cash-flow', {
          params: { period: cfg.period, days: cfg.days },
          signal: controller.signal,
        }),
      ])

      if (cancelled || controller.signal.aborted) return

      const revenueOk = revenueRes.status === 'fulfilled'
      const outstandingOk = outstandingRes.status === 'fulfilled'

      if (revenueOk) setRevenue(revenueRes.value.data ?? null)
      if (outstandingOk) setOutstanding(outstandingRes.value.data ?? null)

      if (jobsRes.status === 'fulfilled' && jobsRes.value) {
        setJobsInProgress(jobsRes.value.data?.total ?? 0)
      } else {
        setJobsInProgress(0)
      }

      if (invoicesRes.status === 'fulfilled') {
        setRecentInvoices(invoicesRes.value.data?.invoices ?? [])
      } else {
        setRecentInvoices([])
      }

      if (bookingsRes.status === 'fulfilled' && bookingsRes.value) {
        setBookings(bookingsRes.value.data?.bookings ?? [])
      } else {
        setBookings([])
      }

      if (cashFlowRes.status === 'fulfilled') {
        // Coerce to numbers — Recharts needs numeric datakeys.
        const items = (cashFlowRes.value.data?.items ?? []).map((p) => ({
          month: p.month,
          month_label: p.month_label,
          revenue: Number(p.revenue ?? 0),
          expenses: Number(p.expenses ?? 0),
        }))
        setChartSeries(items)
      } else {
        setChartSeries([])
      }

      // Only a hard error when both primary KPI calls fail.
      if (!revenueOk && !outstandingOk) {
        setError('Failed to load dashboard data')
      }
      setIsLoading(false)
    }

    fetchDashboard()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [range, selectedBranchId, jobsEnabled, bookingsEnabled])

  /* Overdue KPI — derived from outstanding invoices (OrgAdminDashboard logic). */
  const { overdueAmount, overdueCount } = useMemo(() => {
    const rows = outstanding?.invoices ?? []
    const overdue = rows.filter((inv) => (inv.days_overdue ?? 0) > 0)
    const amount = overdue.reduce((sum, inv) => sum + Number(inv.balance_due ?? 0), 0)
    return { overdueAmount: amount, overdueCount: overdue.length }
  }, [outstanding])

  /* Activity feed — synthesised from the recent invoices already fetched. */
  const activity = useMemo<ActivityEntry[]>(
    () => (recentInvoices ?? []).slice(0, 5).map(invoiceToActivity),
    [recentInvoices],
  )

  if (isLoading) return <Spinner size="lg" label="Loading dashboard" className="py-20" />
  if (error) {
    return (
      <div className="page">
        <AlertBanner variant="error">{error}</AlertBanner>
      </div>
    )
  }

  const orgName = settings?.branding.name ?? 'your business'
  const firstName = (user?.name ?? '').trim().split(/\s+/)[0] || 'there'

  const invoiceCount = revenue?.invoice_count ?? 0
  const outstandingCount = outstanding?.count ?? 0

  return (
    <div className="page">
      {/* Page header — greeting + range segmented control */}
      <div className="page-head mb-gap flex flex-wrap items-end justify-between gap-[18px]">
        <div>
          <div className="mono mb-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-2">
            {todayLabel()}
          </div>
          <h1 className="text-[26px] font-bold text-text">
            {greeting()}, {firstName}
          </h1>
          <p className="mt-1.5 text-[14px] text-muted">Here's how {orgName} is tracking this period.</p>
        </div>
        <div
          className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
          role="group"
          aria-label="Date range"
        >
          {RANGE_ORDER.map((r) => (
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

      {/* KPI row */}
      <div className="mb-gap grid grid-cols-4 gap-gap max-[1080px]:grid-cols-2 max-[520px]:grid-cols-1">
        <KpiCard
          label="Revenue (period)"
          value={formatMoney(revenue?.total_inclusive)}
          money
          sub={`${invoiceCount} invoice${invoiceCount === 1 ? '' : 's'}`}
          icon={DollarIcon}
          tone="green"
        />
        <KpiCard
          label="Outstanding"
          value={formatMoney(outstanding?.total_outstanding)}
          money
          sub={`across ${outstandingCount} invoice${outstandingCount === 1 ? '' : 's'}`}
          icon={DocIcon}
          tone="blue"
        />
        <KpiCard
          label="Overdue"
          value={formatMoney(overdueAmount)}
          money
          sub={`${overdueCount} invoice${overdueCount === 1 ? '' : 's'} overdue`}
          icon={AlertIcon}
          tone="red"
        />
        <KpiCard
          label="Jobs in progress"
          value={String(jobsInProgress)}
          sub={jobsEnabled ? 'active job cards' : 'module disabled'}
          icon={WrenchIcon}
          tone="amber"
        />
      </div>

      {/* grid-2: left (chart + recent invoices) / right (activity + bookings) */}
      <div className="grid grid-cols-[1.7fr_1fr] items-start gap-gap max-[1080px]:grid-cols-1">
        {/* Left stack */}
        <div className="flex flex-col gap-gap">
          {/* Revenue chart */}
          <Card>
            <Card.Head
              title="Revenue"
              action={
                <button
                  type="button"
                  onClick={() => navigate('/reports')}
                  className="text-[12.5px] font-medium text-accent hover:underline"
                >
                  View report →
                </button>
              }
            />
            <div className="flex items-baseline gap-3 px-5 pb-1 pt-[18px]">
              <span className="mono text-[30px] font-semibold tracking-[-0.02em]">
                <span className="text-muted-2">$</span>
                {formatMoney(revenue?.total_inclusive)}
              </span>
              <span className="text-[13px] text-muted">paid this period</span>
            </div>
            <div className="px-3.5 pb-4 pt-2">
              {chartSeries.length === 0 ? (
                <p className="px-1.5 py-12 text-center text-[13px] text-muted">No revenue data for this period</p>
              ) : (
                <div className="h-[200px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartSeries} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                      <defs>
                        <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.2} />
                          <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid vertical={false} stroke="#EEF0F4" strokeWidth={1} />
                      <XAxis
                        dataKey="month_label"
                        tickLine={false}
                        axisLine={false}
                        tick={{ fontSize: 10.5, fill: 'var(--muted-2)', fontFamily: 'var(--font-mono)' }}
                        minTickGap={12}
                      />
                      <YAxis hide domain={['dataMin', 'dataMax']} />
                      <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--border-strong)', strokeWidth: 1 }} />
                      <Area
                        type="monotone"
                        dataKey="revenue"
                        stroke="var(--accent)"
                        strokeWidth={2.5}
                        fill="url(#revenueFill)"
                        dot={false}
                        activeDot={{ r: 4.5, fill: 'var(--accent)', stroke: '#fff', strokeWidth: 2.5 }}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </Card>

          {/* Recent invoices */}
          <Card>
            <Card.Head
              title="Recent invoices"
              action={
                <button
                  type="button"
                  onClick={() => navigate('/invoices')}
                  className="text-[12.5px] font-medium text-accent hover:underline"
                >
                  All invoices →
                </button>
              }
            />
            {recentInvoices.length === 0 ? (
              <p className="px-5 py-10 text-center text-[13px] text-muted">No invoices yet</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                  <caption className="sr-only">Recent invoices</caption>
                  <thead>
                    <tr>
                      <th className="mono border-b border-border px-5 pb-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                        Invoice
                      </th>
                      <th className="mono border-b border-border px-5 pb-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                        Customer
                      </th>
                      <th className="mono border-b border-border px-5 pb-[11px] text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                        Status
                      </th>
                      <th className="mono border-b border-border px-5 pb-[11px] text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">
                        Amount
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentInvoices.map((inv) => (
                      <tr
                        key={inv.id}
                        className="cursor-pointer transition-colors hover:bg-canvas"
                        onClick={() => navigate(`/invoices/${inv.id}`)}
                      >
                        <td className="px-5 py-3">
                          <span className="mono text-[12.5px] text-muted">{inv.invoice_number ?? 'DRAFT'}</span>
                        </td>
                        <td className="px-5 py-3 text-[13.5px] font-semibold text-text">
                          {inv.customer_name ?? '—'}
                        </td>
                        <td className="px-5 py-3">
                          <Badge variant={statusToBadgeVariant(inv.status)}>{inv.status}</Badge>
                        </td>
                        <td className="mono px-5 py-3 text-right text-[13.5px] font-semibold text-text">
                          {formatMoney(inv.total)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        {/* Right stack */}
        <div className="flex flex-col gap-gap">
          {/* Activity feed (synthesised from recent invoices) */}
          <Card>
            <Card.Head
              title="Activity"
              action={
                <button
                  type="button"
                  onClick={() => navigate('/invoices')}
                  className="text-[12.5px] font-medium text-accent hover:underline"
                >
                  All
                </button>
              }
            />
            {activity.length === 0 ? (
              <p className="px-5 py-10 text-center text-[13px] text-muted">No recent activity</p>
            ) : (
              <div>
                {activity.map((a) => {
                  const Icon = a.icon
                  return (
                    <div key={a.id} className="flex gap-3 border-b border-border px-5 py-[13px] last:border-b-0">
                      <div className={cx('grid h-[34px] w-[34px] flex-shrink-0 place-items-center rounded-[9px]', ACTIVITY_DOT_TONE[a.tone])}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13.5px] font-semibold text-text">{a.title}</div>
                        <div className="mt-px truncate text-[12.5px] text-muted">{a.sub}</div>
                      </div>
                      {a.time && <div className="mono whitespace-nowrap text-[11px] text-muted-2">{a.time}</div>}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          {/* Upcoming bookings */}
          <Card>
            <Card.Head
              title="Upcoming bookings"
              action={
                <button
                  type="button"
                  onClick={() => navigate('/bookings')}
                  className="text-[12.5px] font-medium text-accent hover:underline"
                >
                  Schedule →
                </button>
              }
            />
            {!bookingsEnabled ? (
              <p className="px-5 py-10 text-center text-[13px] text-muted">Bookings module is disabled</p>
            ) : bookings.length === 0 ? (
              <p className="px-5 py-10 text-center text-[13px] text-muted">No upcoming bookings</p>
            ) : (
              <div>
                {bookings.map((b) => {
                  const when = b.scheduled_at ?? b.start_time
                  const date = when ? new Date(when) : null
                  const day = date ? date.toLocaleDateString('en-NZ', { day: '2-digit' }) : '—'
                  const month = date ? date.toLocaleDateString('en-NZ', { month: 'short' }) : ''
                  const time = date
                    ? date.toLocaleTimeString('en-NZ', { hour: '2-digit', minute: '2-digit' })
                    : ''
                  const sub = [b.customer_name, b.vehicle_rego].filter(Boolean).join(' · ')
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => navigate(`/bookings/${b.id}`)}
                      className="flex w-full items-center gap-3 border-b border-border px-5 py-[13px] text-left transition-colors last:border-b-0 hover:bg-canvas"
                    >
                      <div className="w-[46px] flex-shrink-0 text-center">
                        <div className="mono text-[18px] font-semibold leading-none">{day}</div>
                        <div className="mono text-[10px] uppercase text-muted-2">{month}</div>
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[13.5px] font-semibold text-text">{b.service_type ?? 'Booking'}</div>
                        {sub && <div className="mt-px truncate text-[12px] text-muted">{sub}</div>}
                      </div>
                      {time && <div className="mono whitespace-nowrap text-[13.5px] font-semibold text-text">{time}</div>}
                    </button>
                  )
                })}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

export default MainDashboard
