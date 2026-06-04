import { useMemo } from 'react'
import { Spinner, cx } from '@/components/ui'
import SimpleBarChart from './SimpleBarChart'
import ReportLibrary from './ReportLibrary'
import useReportsOverview, {
  type ReportsRange,
  type RevenueCategoryPoint,
} from './useReportsOverview'

/* ============================================================
   ReportsPage — rebuilt Reports landing (Task 19.2).
   ------------------------------------------------------------
   Design source: OraInvoice_Handoff/app/Reports.html
   Section: design.md §"E1 — Rebuilt ReportsPage landing"

   Layout:
     • page-head: eyebrow "Overview" + h1 "Reports" + sub
       + range segmented control (7D / 30D / QTR / YR)
     • KPI row (4 cards): Revenue · Gross profit · Avg invoice · Jobs completed
       (Revenue + Avg invoice come from /reports/revenue via useReportsOverview;
        Gross profit + Jobs completed have no backend source yet — the hook
        returns null and we render the "—" placeholder, R15.3.)
     • two-col grid: Revenue by month (SimpleBarChart) + Revenue by category
       (CSS progress bars, design §E1)
     • ReportLibrary (Task 20 will fill the stub with the grouped cards).

   Tokens: cards `bg-card border border-border rounded-card shadow-card`,
   the `--gap` rhythm (`gap-gap`/`mb-gap`) and `mono` for numbers, range
   segmented control styled as the prototype `.seg` (rounded-ctl border,
   3px inner padding, `bg-accent-soft text-accent` on the active segment).
   Currency formatted via `Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' })`.

   Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 21.1
   ============================================================ */

const RANGE_OPTIONS: ReportsRange[] = ['7D', '30D', 'QTR', 'YR']

const FALLBACK_PLACEHOLDER = '—'

const currencyFormatter = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

/** Format a money number as NZ currency, or the dash placeholder when null. */
function formatMoney(value: number | null): string {
  if (value == null) return FALLBACK_PLACEHOLDER
  return currencyFormatter.format(value)
}

/** Format a count, or the dash placeholder when null. */
function formatCount(value: number | null): string {
  if (value == null) return FALLBACK_PLACEHOLDER
  return value.toLocaleString('en-NZ')
}

/* ── Inline KPI icons (no icon dependency — matches MainDashboard convention) ── */

interface IconProps {
  className?: string
}

function DollarIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M12 1v22M17 5H9.5a3.5 3.5 0 100 7h5a3.5 3.5 0 110 7H6" />
    </svg>
  )
}
function ChartIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M3 3v18h18" />
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
function CheckIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M9 12l2 2 4-4M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
    </svg>
  )
}

/* ── KPI card ── */

type KpiTone = 'green' | 'blue' | 'purple' | 'amber'

const KPI_ICON_TONE: Record<KpiTone, string> = {
  green: 'bg-ok-soft text-ok',
  blue: 'bg-accent-soft text-accent',
  purple: 'bg-purple-soft text-purple',
  amber: 'bg-warn-soft text-warn',
}

interface KpiCardProps {
  label: string
  /** Pre-formatted display value (currency string or numeric string or "—"). */
  value: string
  icon: React.ComponentType<IconProps>
  tone: KpiTone
  loading?: boolean
}

/** Single KPI tile — mirrors prototype `.kpi` (label + tinted icon, mono value). */
function KpiCard({ label, value, icon: Icon, tone, loading }: KpiCardProps) {
  return (
    <div className="rounded-card border border-border bg-card p-5 shadow-card">
      <div className="mb-3.5 flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-muted">{label}</span>
        <span className={cx('grid h-8 w-8 place-items-center rounded-[9px]', KPI_ICON_TONE[tone])}>
          <Icon className="h-[17px] w-[17px]" />
        </span>
      </div>
      <div className="mono text-[27px] font-semibold leading-none tracking-[-0.02em] text-text">
        {loading ? <span className="text-muted-2">…</span> : value}
      </div>
    </div>
  )
}

/* ── Range segmented control (prototype `.seg`) ── */

interface RangeSegProps {
  value: ReportsRange
  onChange: (range: ReportsRange) => void
}

function RangeSeg({ value, onChange }: RangeSegProps) {
  return (
    <div
      className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
      role="group"
      aria-label="Date range"
    >
      {RANGE_OPTIONS.map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={value === r}
          onClick={() => onChange(r)}
          className={cx(
            'mono rounded-[7px] px-[13px] py-1.5 text-[12.5px] font-medium transition-colors',
            value === r ? 'bg-accent-soft text-accent' : 'text-muted hover:text-text',
          )}
        >
          {r}
        </button>
      ))}
    </div>
  )
}

/* ── Revenue by category panel — CSS progress bars (prototype `.progress`) ── */

const CATEGORY_COLOURS: Record<string, string> = {
  Labour: 'var(--accent)',
  Parts: 'var(--ok)',
  Tyres: 'var(--warn)',
  Other: 'var(--purple)',
}

interface RevenueByCategoryCardProps {
  data: RevenueCategoryPoint[]
}

function RevenueByCategoryCard({ data }: RevenueByCategoryCardProps) {
  // Compute share-of-total percentages for the progress bars (R15.4).
  const total = data.reduce((sum, row) => sum + (row.revenue ?? 0), 0)

  return (
    <section className="rounded-card border border-border bg-card shadow-card">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-base font-semibold text-text">Revenue by category</h2>
      </div>
      <div className="px-5 py-4">
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            No category data for this period.
          </p>
        ) : (
          <ul className="space-y-3">
            {data.map((row) => {
              const pct = total > 0 ? Math.round(((row.revenue ?? 0) / total) * 100) : 0
              const colour = CATEGORY_COLOURS[row.category] ?? 'var(--accent)'
              return (
                <li key={row.category}>
                  <div className="mb-1.5 flex items-center justify-between text-[13px] text-text">
                    <span>{row.category}</span>
                    <span className="mono font-semibold">{pct}%</span>
                  </div>
                  <div
                    className="h-2 w-full overflow-hidden rounded-full bg-canvas"
                    role="progressbar"
                    aria-label={`${row.category} share`}
                    aria-valuenow={pct}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{ width: `${pct}%`, background: colour }}
                    />
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

/* ── Revenue by month panel — SimpleBarChart ── */

interface RevenueByMonthCardProps {
  data: { month: string; revenue: number }[]
}

function RevenueByMonthCard({ data }: RevenueByMonthCardProps) {
  return (
    <section className="rounded-card border border-border bg-card shadow-card">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-base font-semibold text-text">Revenue by month</h2>
      </div>
      <div className="px-5 py-4">
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            No monthly revenue for this period.
          </p>
        ) : (
          <SimpleBarChart
            title="Monthly revenue breakdown"
            items={data.map((m) => ({ label: m.month, value: m.revenue ?? 0 }))}
            formatValue={(v) => currencyFormatter.format(v)}
          />
        )}
      </div>
    </section>
  )
}

/* ── Page ── */

/**
 * Rebuilt Reports landing page — overview KPIs + revenue panels +
 * grouped Report Library (stubbed in Task 19, filled in Task 20).
 *
 * Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 21.1
 * Design: §"E1 — Rebuilt ReportsPage landing" TSX skeleton
 */
export default function ReportsPage() {
  const { range, setRange, kpis, monthly, categories, loading, error } = useReportsOverview('30D')

  // Memoise the monthly array fed into the chart so a re-render with the same
  // backend data does not force a fresh array reference.
  const monthlyPoints = useMemo(
    () => (monthly ?? []).map((m) => ({ month: m.month, revenue: m.revenue ?? 0 })),
    [monthly],
  )

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      {/* Page head — eyebrow + title + range segmented control */}
      <header className="mb-gap flex flex-wrap items-end justify-between gap-[18px] no-print">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-2">
            Overview
          </p>
          <h1 className="mt-1 text-[26px] font-bold text-text">Reports</h1>
          <p className="mt-1 text-sm text-muted">Financial &amp; operational insights</p>
        </div>
        <RangeSeg value={range} onChange={setRange} />
      </header>

      {error && (
        <div
          className="mb-gap rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* KPI row — 4 cards (R15.2) */}
      <div className="mb-gap grid grid-cols-4 gap-gap max-[1080px]:grid-cols-2 max-[520px]:grid-cols-1">
        <KpiCard
          label="Revenue"
          value={formatMoney(kpis.revenue)}
          icon={DollarIcon}
          tone="green"
          loading={loading}
        />
        <KpiCard
          label="Gross profit"
          value={formatMoney(kpis.gross_profit)}
          icon={ChartIcon}
          tone="blue"
          loading={loading}
        />
        <KpiCard
          label="Avg invoice"
          value={formatMoney(kpis.average_invoice)}
          icon={DocIcon}
          tone="purple"
          loading={loading}
        />
        <KpiCard
          label="Jobs completed"
          value={formatCount(kpis.jobs_completed)}
          icon={CheckIcon}
          tone="amber"
          loading={loading}
        />
      </div>

      {/* Two-col overview grid: Revenue by month (1.5fr) + Revenue by category (1fr) */}
      <div className="mb-gap grid grid-cols-1 gap-gap lg:grid-cols-[1.5fr_1fr]">
        {loading && monthlyPoints.length === 0 ? (
          <section className="rounded-card border border-border bg-card p-8 shadow-card">
            <Spinner label="Loading revenue by month" />
          </section>
        ) : (
          <RevenueByMonthCard data={monthlyPoints} />
        )}
        {loading && (categories ?? []).length === 0 ? (
          <section className="rounded-card border border-border bg-card p-8 shadow-card">
            <Spinner label="Loading revenue by category" />
          </section>
        ) : (
          <RevenueByCategoryCard data={categories ?? []} />
        )}
      </div>

      {/* Report library — Task 20 fills the stub with the grouped cards (R15.6) */}
      <ReportLibrary />
    </div>
  )
}
