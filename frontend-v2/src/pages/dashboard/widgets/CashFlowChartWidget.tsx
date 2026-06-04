/**
 * Cash Flow Chart Widget — redesigned to match the prototype Revenue widget.
 *
 * Design source: OraInvoice_Handoff/app/Dashboard.html (the "Revenue" card):
 *   • a chart-meta header — big mono `$value` + a ▲/▼ delta tag + a caption
 *   • a smooth area line with an accent gradient fill (`--accent` 0.20 → 0),
 *     horizontal gridlines (#EEF0F4) and a persistent endpoint dot
 *     (r 4.5, accent fill, white stroke 2.5)
 *   • an x-axis of period buckets
 *
 * Logic source: frontend/src/pages/dashboard/widgets/CashFlowChartWidget.tsx.
 * The per-period self-fetch from `GET /dashboard/widgets/cash-flow?period=…&days=…`
 * is preserved (AbortController + CanceledError guard, `res.data?.items ?? []`).
 * What changed (per the user's redesign request):
 *   • The widget's own Daily/Weekly/Monthly chips are removed — the period +
 *     window are now driven by the page-level 7D/30D/QTR/YR range control in
 *     the dashboard head (passed via the `range` prop). The mapping lives in
 *     DASHBOARD_RANGE_CONFIG (types.ts), shared with MainDashboard.
 *   • The bar chart (revenue + expenses) becomes an accent area chart of
 *     revenue, matching the prototype Revenue widget.
 *
 * The big value (sum of revenue over the range) and the delta tag (recent half
 * vs older half of the series) are DERIVED from the already-fetched data — no
 * figures are fabricated.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
 */

import { useState, useEffect } from 'react'
import {
  Area,
  AreaChart,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import apiClient from '@/api/client'
import { WidgetCard } from './WidgetCard'
import { cx } from '@/components/ui'
import type { CashFlowMonth, WidgetDataSection, DashboardRange } from './types'
import { DASHBOARD_RANGE_CONFIG } from './types'

interface CashFlowChartWidgetProps {
  data: WidgetDataSection<CashFlowMonth> | undefined | null
  isLoading: boolean
  error: string | null
  /** Page-level range filter (7D/30D/QTR/YR). Defaults to 30D. */
  range?: DashboardRange
}

function ChartIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
    </svg>
  )
}

/** Whole-dollar money for the big value + axis/tooltip. */
function formatMoney0(value: number | null | undefined): string {
  return `${(value ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

interface ChartTooltipProps {
  active?: boolean
  payload?: Array<{ value?: number | string }>
  label?: string | number
}

function ChartTooltip({ active, payload, label }: ChartTooltipProps) {
  if (!active || !(payload ?? []).length) return null
  const value = payload?.[0]?.value
  const numeric = typeof value === 'number' ? value : Number(value ?? 0)
  return (
    <div className="rounded-ctl border border-border bg-card px-3 py-2 shadow-pop">
      <p className="text-[11px] font-medium text-muted">{label}</p>
      <p className="mono text-[13px] font-semibold text-text">${formatMoney0(numeric)}</p>
    </div>
  )
}

/** Persistent endpoint dot (prototype: r 4.5, accent fill, white stroke). Only
 *  drawn on the final point of the series; every other index renders nothing. */
interface AreaDotProps {
  cx?: number
  cy?: number
  index?: number
}
function makeEndpointDot(lastIndex: number) {
  return function EndpointDot({ cx: x, cy: y, index }: AreaDotProps) {
    if (index !== lastIndex || x == null || y == null) return <g />
    return <circle cx={x} cy={y} r={4.5} fill="var(--accent)" stroke="#fff" strokeWidth={2.5} />
  }
}

export function CashFlowChartWidget({
  data,
  isLoading: initialLoading,
  error: initialError,
  range = '30D',
}: CashFlowChartWidgetProps) {
  const [chartData, setChartData] = useState<CashFlowMonth[]>(data?.items ?? [])
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  // Refetch whenever the page-level range changes. The initial `data` prop
  // (fetched by the aggregator at the default monthly window) seeds the first
  // paint; once the range drives a fetch the response replaces it.
  useEffect(() => {
    const controller = new AbortController()

    const fetchData = async () => {
      setLoading(true)
      setFetchError(null)
      try {
        const config = DASHBOARD_RANGE_CONFIG[range]
        const res = await apiClient.get<{ items: CashFlowMonth[]; total: number }>(
          `/dashboard/widgets/cash-flow?period=${config.period}&days=${config.days}`,
          { signal: controller.signal },
        )
        setChartData(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name === 'CanceledError') return
        setFetchError('Failed to load cash flow data')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    fetchData()
    return () => controller.abort()
  }, [range])

  const items = chartData.map((p) => ({
    month: p.month,
    month_label: p.month_label,
    revenue: Number(p.revenue ?? 0),
    expenses: Number(p.expenses ?? 0),
  }))
  const isWidgetLoading = initialLoading || loading
  const widgetError = initialError || fetchError

  // Big value = total revenue over the range. Delta tag = recent half vs older
  // half of the series (both derived from real data; tag hidden when the older
  // half is zero to avoid a divide-by-zero / meaningless 100%).
  const revenues = items.map((p) => p.revenue)
  const totalRevenue = revenues.reduce((sum, v) => sum + v, 0)
  const mid = Math.floor(revenues.length / 2)
  const olderSum = revenues.slice(0, mid).reduce((sum, v) => sum + v, 0)
  const recentSum = revenues.slice(mid).reduce((sum, v) => sum + v, 0)
  const deltaPct = olderSum > 0 ? ((recentSum - olderSum) / olderSum) * 100 : null
  const deltaUp = (deltaPct ?? 0) >= 0

  return (
    <WidgetCard
      title="Cash Flow"
      icon={ChartIcon}
      actionLink={{ label: 'View report →', to: '/reports' }}
      isLoading={isWidgetLoading}
      error={widgetError}
    >
      {items.length === 0 ? (
        <p className="text-[13px] text-muted">No financial data available</p>
      ) : (
        <>
          {/* chart-meta — big value + delta tag + caption (prototype Revenue) */}
          <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="mono text-[30px] font-semibold leading-none tracking-[-0.02em] text-text">
              <span className="text-muted-2">$</span>
              {formatMoney0(totalRevenue)}
            </span>
            {deltaPct !== null && (
              <span
                className={cx(
                  'mono rounded-[6px] px-2 py-0.5 text-[12px] font-medium',
                  deltaUp ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger',
                )}
              >
                {deltaUp ? '▲' : '▼'} {Math.abs(deltaPct).toFixed(1)}%
              </span>
            )}
            <span className="text-[13px] text-muted">revenue this period</span>
          </div>

          <div className="h-[200px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={items} margin={{ top: 10, right: 8, left: 8, bottom: 0 }}>
                <defs>
                  <linearGradient id="cashFlowFill" x1="0" y1="0" x2="0" y2="1">
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
                  fill="url(#cashFlowFill)"
                  dot={makeEndpointDot(items.length - 1)}
                  activeDot={{ r: 4.5, fill: 'var(--accent)', stroke: '#fff', strokeWidth: 2.5 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </WidgetCard>
  )
}
