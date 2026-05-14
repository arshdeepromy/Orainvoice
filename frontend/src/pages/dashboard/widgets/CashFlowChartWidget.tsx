/**
 * Cash Flow Chart Widget with period selector
 *
 * Renders a bar chart with revenue (green) and expenses (red).
 * Supports daily/weekly/monthly period selection.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
 */

import { useState, useEffect, useRef } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import apiClient from '@/api/client'
import { WidgetCard } from './WidgetCard'
import type { CashFlowMonth, WidgetDataSection } from './types'

interface CashFlowChartWidgetProps {
  data: WidgetDataSection<CashFlowMonth> | undefined | null
  isLoading: boolean
  error: string | null
}

type Period = 'daily' | 'weekly' | 'monthly'

const PERIOD_CONFIG: Record<Period, { label: string; days: number }> = {
  daily: { label: 'Daily', days: 30 },
  weekly: { label: 'Weekly', days: 90 },
  monthly: { label: 'Monthly', days: 180 },
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

export function CashFlowChartWidget({ data, isLoading: initialLoading, error: initialError }: CashFlowChartWidgetProps) {
  const [period, setPeriod] = useState<Period>('monthly')
  const [chartData, setChartData] = useState<CashFlowMonth[]>(data?.items ?? [])
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const abortRef = useRef<AbortController>(undefined)
  const initialDataUsed = useRef(false)

  // Use initial data for monthly (default) on first load
  useEffect(() => {
    if (!initialDataUsed.current && (data?.items ?? []).length > 0) {
      setChartData(data?.items ?? [])
      initialDataUsed.current = true
    }
  }, [data])

  // Fetch when period changes
  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller

    const fetchData = async () => {
      setLoading(true)
      setFetchError(null)
      try {
        const config = PERIOD_CONFIG[period]
        const res = await apiClient.get<{ items: CashFlowMonth[]; total: number }>(
          `/dashboard/widgets/cash-flow?period=${period}&days=${config.days}`,
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
  }, [period])

  const items = chartData
  const isWidgetLoading = initialLoading || loading
  const widgetError = initialError || fetchError

  return (
    <WidgetCard
      title="Cash Flow"
      icon={ChartIcon}
      isLoading={isWidgetLoading}
      error={widgetError}
    >
      {/* Period selector */}
      <div className="flex gap-1 mb-3">
        {(Object.entries(PERIOD_CONFIG) as [Period, { label: string; days: number }][]).map(([key, config]) => (
          <button
            key={key}
            onClick={() => setPeriod(key)}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              period === key
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {config.label}
          </button>
        ))}
      </div>

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
