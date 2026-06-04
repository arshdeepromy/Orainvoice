import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Select, PrintButton } from '@/components/ui'
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

      {error && <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading hospitality report" /></div>}

      {!loading && data && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Hospitality report — {sub.replace(/_/g, ' ')}</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Item</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Count</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Value</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).length === 0 && !data.avg_order_value ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-sm text-muted">No data.</td></tr>
              ) : data.avg_order_value != null ? (
                <>
                  <tr className="border-b border-border hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text">Average Order Value</td>
                    <td className="px-4 py-3 text-sm text-muted text-right mono">{data.total_orders}</td>
                    <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(data.avg_order_value)}</td>
                  </tr>
                  <tr className="border-b border-border last:border-b-0 hover:bg-canvas bg-accent-soft">
                    <td className="px-4 py-3 text-sm font-medium text-text">Total Revenue</td>
                    <td className="px-4 py-3 text-sm text-muted text-right" />
                    <td className="px-4 py-3 text-sm font-medium text-text text-right mono">{fmt(data.total_revenue)}</td>
                  </tr>
                </>
              ) : (
                (data.items || []).map((item: any, i: number) => (
                  <tr key={i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text">{item.table_number || item.item_name || item.staff_name || '-'}</td>
                    <td className="px-4 py-3 text-sm text-muted text-right mono">{item.turnover_count ?? item.order_count ?? item.tip_count ?? '-'}</td>
                    <td className="px-4 py-3 text-sm text-text text-right mono">{item.avg_prep_minutes != null ? `${item.avg_prep_minutes} min` : fmt(item.total_tips ?? 0)}</td>
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
