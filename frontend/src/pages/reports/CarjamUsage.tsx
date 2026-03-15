import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface CarjamData {
  total_lookups: number
  included_in_plan: number
  overage_lookups: number
  overage_charge: number
  daily_breakdown: { date: string; lookups: number }[]
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth(), 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Carjam API usage report — lookups, included, overage, and daily breakdown.
 * Requirements: 45.1
 */
export default function CarjamUsage() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<CarjamData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<CarjamData>('/reports/carjam-usage', {
        params: { from: range.from, to: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load Carjam usage report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4 no-print">Carjam API lookup usage and overage charges.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/carjam-usage" params={{ from: range.from, to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading Carjam usage report" /></div>}

      {!loading && data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total Lookups</p>
              <p className="text-2xl font-semibold text-gray-900">{data.total_lookups}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Included in Plan</p>
              <p className="text-2xl font-semibold text-gray-900">{data.included_in_plan}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Overage Lookups</p>
              <p className="text-2xl font-semibold text-amber-600">{data.overage_lookups}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Overage Charge</p>
              <p className="text-2xl font-semibold text-red-600">{fmt(data.overage_charge)}</p>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Daily Lookups</h3>
            {data.daily_breakdown && data.daily_breakdown.length > 0 ? (
              <SimpleBarChart
                title="Daily Carjam lookups"
                items={data.daily_breakdown.map((d) => ({
                  label: new Date(d.date).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }),
                  value: d.lookups,
                }))}
              />
            ) : (
              <p className="text-sm text-gray-500 py-8 text-center">No daily data available for this period.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
