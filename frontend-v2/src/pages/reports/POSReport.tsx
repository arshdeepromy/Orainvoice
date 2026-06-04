import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Select, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type SubReport = 'daily_sales_summary' | 'session_reconciliation' | 'hourly_sales_heatmap'

const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'

function defaultRange(): DateRange {
  const now = new Date()
  return { from: now.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

/**
 * POS reports: daily sales, session reconciliation, hourly heatmap.
 * Requirements: Task 54.18
 */
export default function POSReport() {
  const [sub, setSub] = useState<SubReport>('daily_sales_summary')
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
      setError('Failed to load POS report.')
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
              { value: 'daily_sales_summary', label: 'Daily Sales Summary' },
              { value: 'session_reconciliation', label: 'Session Reconciliation' },
              { value: 'hourly_sales_heatmap', label: 'Hourly Sales Heatmap' },
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
      {loading && <div className="py-16"><Spinner label="Loading POS report" /></div>}

      {!loading && data && sub === 'daily_sales_summary' && (
        <div>
          {data.grand_total != null && (
            <div className="rounded-card border border-border bg-card p-4 mb-4 shadow-card">
              <p className="text-sm text-muted">Grand Total</p>
              <p className="text-2xl font-semibold text-text mono">{fmt(data.grand_total)}</p>
            </div>
          )}
          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Sales by payment method</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Payment Method</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Count</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
                </tr>
              </thead>
              <tbody>
                {(data.by_payment_method || []).map((item: any, i: number) => (
                  <tr key={item.payment_method || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text capitalize">{item.payment_method}</td>
                    <td className="px-4 py-3 text-sm text-muted text-right mono">{item.count}</td>
                    <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(item.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && data && sub === 'hourly_sales_heatmap' && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Hourly sales heatmap</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Hour</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Transactions</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).map((item: any, i: number) => (
                <tr key={item.hour ?? i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3 text-sm text-text mono">{String(item.hour).padStart(2, '0')}:00</td>
                  <td className="px-4 py-3 text-sm text-muted text-right mono">{item.count}</td>
                  <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(item.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && data && sub === 'session_reconciliation' && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Session reconciliation</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Session</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Expected</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Actual</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Variance</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).map((item: any, i: number) => (
                <tr key={i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                  <td className="px-4 py-3 text-sm text-text">{item.user_name || item.session_id?.slice(0, 8) || '-'}</td>
                  <td className="px-4 py-3 text-sm text-muted text-right mono">{fmt(item.expected_cash)}</td>
                  <td className="px-4 py-3 text-sm text-muted text-right mono">{fmt(item.actual_cash ?? 0)}</td>
                  <td className={`px-4 py-3 text-sm text-right font-medium mono ${item.variance < 0 ? 'text-danger' : 'text-ok'}`}>
                    {fmt(item.variance)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
