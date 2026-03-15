import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface ServiceStat {
  service_name: string
  count: number
  revenue: number
}

interface TopServicesData {
  services: ServiceStat[]
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Top services report — ranked by revenue with count.
 * Requirements: 45.1
 */
export default function TopServices() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<TopServicesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<TopServicesData>('/reports/top-services', {
        params: { start_date: range.from, end_date: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load top services report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4 no-print">Services ranked by revenue.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/top-services" params={{ start_date: range.from, end_date: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading top services report" /></div>}

      {!loading && data && (
        <>
          {/* Table */}
          <div className="overflow-x-auto rounded-lg border border-gray-200 mb-6">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Top services by revenue</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">#</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Service</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Count</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Revenue</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {!data.services || data.services.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-sm text-gray-500">
                      No service data for this period.
                    </td>
                  </tr>
                ) : (
                  data.services.map((s, i) => (
                    <tr key={`${s.service_name}-${i}`} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-500">{i + 1}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{s.service_name}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 text-right">{s.count}</td>
                      <td className="px-4 py-3 text-sm text-gray-900 text-right">{fmt(s.revenue)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chart */}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Revenue by Service</h3>
            {data.services && data.services.length > 0 ? (
              <SimpleBarChart
                title="Revenue by service"
                items={data.services.map((s) => ({ label: s.service_name, value: s.revenue }))}
                formatValue={fmt}
              />
            ) : (
              <p className="text-sm text-gray-500 py-8 text-center">No service data available for this period.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
