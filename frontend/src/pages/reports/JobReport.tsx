import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Select, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type SubReport = 'job_profitability' | 'jobs_by_status' | 'avg_completion_time' | 'staff_utilisation'

const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now)
  from.setMonth(from.getMonth() - 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

/**
 * Job reports: profitability, status summary, completion time, staff utilisation.
 * Requirements: Task 54.18
 */
export default function JobReport() {
  const [sub, setSub] = useState<SubReport>('job_profitability')
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
      setError('Failed to load job report.')
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
              { value: 'job_profitability', label: 'Job Profitability' },
              { value: 'jobs_by_status', label: 'Jobs by Status' },
              { value: 'avg_completion_time', label: 'Avg Completion Time' },
              { value: 'staff_utilisation', label: 'Staff Utilisation' },
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
      {loading && <div className="py-16"><Spinner label="Loading job report" /></div>}

      {!loading && data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Job report — {sub.replace(/_/g, ' ')}</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Item</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Value</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(data.items || []).length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-sm text-gray-500">No data for this period.</td></tr>
              ) : (
                (data.items || []).map((item: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">{item.job_number || item.status || item.trade_category || item.staff_name || '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-700 text-right">
                      {item.revenue != null ? fmt(item.revenue) : item.count ?? item.avg_days ?? fmt(item.total_hours ?? 0)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900 text-right">
                      {item.profit != null ? fmt(item.profit) : item.utilisation_percent != null ? `${item.utilisation_percent}%` : '-'}
                    </td>
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
