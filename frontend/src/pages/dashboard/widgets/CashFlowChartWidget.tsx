/**
 * Cash Flow Chart Widget
 *
 * Renders a bar chart using recharts with monthly revenue (green)
 * and expenses (red) for the last 6 months. X-axis: month names,
 * Y-axis: NZD currency values. Tooltip on hover.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { WidgetCard } from './WidgetCard'
import type { CashFlowMonth, WidgetDataSection } from './types'

interface CashFlowChartWidgetProps {
  data: WidgetDataSection<CashFlowMonth> | undefined | null
  isLoading: boolean
  error: string | null
}

function ChartIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
    </svg>
  )
}

function formatCurrency(value: number | null | undefined): string {
  return `$${((value ?? 0)).toLocaleString('en-NZ', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

interface TooltipPayloadEntry {
  name?: string
  value?: number
  color?: string
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadEntry[]
  label?: string
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !(payload ?? []).length) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <p className="text-xs font-medium text-gray-700 mb-1">{label}</p>
      {(payload ?? []).map((entry, idx) => (
        <p key={idx} className="text-xs" style={{ color: entry?.color }}>
          {entry?.name}: {formatCurrency(entry?.value)}
        </p>
      ))}
    </div>
  )
}

export function CashFlowChartWidget({ data, isLoading, error }: CashFlowChartWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Cash Flow"
      icon={ChartIcon}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-sm text-gray-500">No financial data available</p>
      ) : (
        <div className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={items} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="month_label"
                tick={{ fontSize: 11, fill: '#6b7280' }}
                axisLine={{ stroke: '#e5e7eb' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#6b7280' }}
                axisLine={{ stroke: '#e5e7eb' }}
                tickLine={false}
                tickFormatter={(v) => formatCurrency(v)}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="revenue" name="Revenue" fill="#22c55e" radius={[2, 2, 0, 0]} />
              <Bar dataKey="expenses" name="Expenses" fill="#ef4444" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </WidgetCard>
  )
}
