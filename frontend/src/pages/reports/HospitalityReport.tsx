import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Select, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type SubReport = 'table_turnover' | 'avg_order_value' | 'kitchen_prep_times' | 'tip_summary'

const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

/**
 * Hospitality reports: table turnover, avg order value, kitchen prep, tips.
 * Requirements: Task 54.18
 */
export default function HospitalityReport() {
  const [sub, setSub] = useState<SubReport>('table_turnover')
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/reports/${sub}`, {
        params: { date_from: range.from, date_to: range.to },
      })
      setData(res.data?.data ?? res.data)
    } catch {
      setError('Failed to load hospitality report.')
    } finally {
      setLoading(false)
    }
  }, [sub, range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div data-print-content>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <div className="flex gap-3 items-end">
          <Select
            label="Report"
            value={sub}
            onChange={(e) => setSub(e.target.value as SubReport)}
            options={[
              { value: 'table_turnover', label: 'Table Turnover' },
              { value: 'avg_order_value', label: 'Avg Order Value' },
              { value: 'kitchen_prep_times', label: 'Kitchen Prep Times' },
              { value: 'tip_summary', label: 'Tip Summary' },
            ]}
          />
          <DateRangeFilter value={range} onChange={setRange} />
        </div>
        <div className="flex items-center gap-2">
          <ExportButtons endpoint={`/reports/${sub}`} params={{ date_from: range.from, date_to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading hospitality report" /></div>}

      {!loading && data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Hospitality report — {sub.replace(/_/g, ' ')}</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Item</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Count</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(data.items || []).length === 0 && !data.avg_order_value ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-sm text-gray-500">No data.</td></tr>
              ) : data.avg_order_value != null ? (
                <>
                  <tr className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">Average Order Value</td>
                    <td className="px-4 py-3 text-sm text-gray-700 text-right">{data.total_orders}</td>
                    <td className="px-4 py-3 text-sm text-gray-900 text-right">{fmt(data.avg_order_value)}</td>
                  </tr>
                  <tr className="hover:bg-gray-50 bg-blue-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">Total Revenue</td>
                    <td className="px-4 py-3 text-sm text-gray-700 text-right" />
                    <td className="px-4 py-3 text-sm font-medium text-gray-900 text-right">{fmt(data.total_revenue)}</td>
                  </tr>
                </>
              ) : (
                (data.items || []).map((item: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">{item.table_number || item.item_name || item.staff_name || '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-700 text-right">{item.turnover_count ?? item.order_count ?? item.tip_count ?? '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-900 text-right">{item.avg_prep_minutes != null ? `${item.avg_prep_minutes} min` : fmt(item.total_tips ?? 0)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
