import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Select, PrintButton } from '../../components/ui'
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

      {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading POS report" /></div>}

      {!loading && data && sub === 'daily_sales_summary' && (
        <div>
          {data.grand_total != null && (
            <div className="rounded-lg border border-gray-200 bg-white p-4 mb-4">
              <p className="text-sm text-gray-500">Grand Total</p>
              <p className="text-2xl font-semibold">{fmt(data.grand_total)}</p>
            </div>
          )}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Sales by payment method</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Payment Method</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Count</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {(data.by_payment_method || []).map((item: any, i: number) => (
                  <tr key={item.payment_method || i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900 capitalize">{item.payment_method}</td>
                    <td className="px-4 py-3 text-sm text-gray-700 text-right">{item.count}</td>
                    <td className="px-4 py-3 text-sm text-gray-900 text-right">{fmt(item.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && data && sub === 'hourly_sales_heatmap' && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Hourly sales heatmap</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Hour</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Transactions</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(data.items || []).map((item: any, i: number) => (
                <tr key={item.hour ?? i} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">{String(item.hour).padStart(2, '0')}:00</td>
                  <td className="px-4 py-3 text-sm text-gray-700 text-right">{item.count}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 text-right">{fmt(item.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && data && sub === 'session_reconciliation' && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Session reconciliation</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Session</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Expected</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Actual</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase text-gray-500">Variance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(data.items || []).map((item: any, i: number) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">{item.user_name || item.session_id?.slice(0, 8) || '-'}</td>
                  <td className="px-4 py-3 text-sm text-gray-700 text-right">{fmt(item.expected_cash)}</td>
                  <td className="px-4 py-3 text-sm text-gray-700 text-right">{fmt(item.actual_cash ?? 0)}</td>
                  <td className={`px-4 py-3 text-sm text-right font-medium ${item.variance < 0 ? 'text-red-600' : 'text-green-600'}`}>
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
