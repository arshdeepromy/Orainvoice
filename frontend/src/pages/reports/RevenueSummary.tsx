import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface RevenueData {
  total_revenue: number
  total_gst: number
  total_invoices: number
  monthly_breakdown: { month: string; revenue: number }[]
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now)
  from.setMonth(from.getMonth() - 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

/**
 * Revenue summary report — total revenue, GST collected, invoice count,
 * and monthly breakdown bar chart.
 * Requirements: 45.1, 45.2, 45.3, 45.4
 */
export default function RevenueSummary() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<RevenueData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetch = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<RevenueData>('/reports/revenue', {
        params: { from: range.from, to: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load revenue report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetch() }, [fetch])

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4">Total revenue, GST collected, and monthly breakdown.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/revenue" params={{ from: range.from, to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading revenue report" /></div>}

      {!loading && data && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total Revenue</p>
              <p className="text-2xl font-semibold text-gray-900">{fmt(data.total_revenue)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">GST Collected</p>
              <p className="text-2xl font-semibold text-gray-900">{fmt(data.total_gst)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Invoices</p>
              <p className="text-2xl font-semibold text-gray-900">{data.total_invoices}</p>
            </div>
          </div>

          {/* Monthly chart */}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Monthly Revenue</h3>
            <SimpleBarChart
              title="Monthly revenue breakdown"
              items={data.monthly_breakdown.map((m) => ({ label: m.month, value: m.revenue }))}
              formatValue={fmt}
            />
          </div>
        </>
      )}
    </div>
  )
}
