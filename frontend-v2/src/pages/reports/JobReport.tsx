import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Select, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type SubReport = 'job_profitability' | 'jobs_by_status' | 'avg_completion_time' | 'staff_utilisation'

const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
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

      {error && <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading job report" /></div>}

      {!loading && data && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Job report — {sub.replace(/_/g, ' ')}</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Item</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Value</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-sm text-muted">No data for this period.</td></tr>
              ) : (
                (data.items || []).map((item: any, i: number) => (
                  <tr key={i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text">{item.job_number || item.status || item.trade_category || item.staff_name || '-'}</td>
                    <td className="px-4 py-3 text-sm text-muted text-right mono">
                      {item.revenue != null ? fmt(item.revenue) : item.count ?? item.avg_days ?? fmt(item.total_hours ?? 0)}
                    </td>
                    <td className="px-4 py-3 text-sm text-text text-right mono">
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
