import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Select, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type SubReport = 'stock_valuation' | 'stock_movement_summary' | 'low_stock' | 'dead_stock'

const fmt = (v: number) => v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now)
  from.setMonth(from.getMonth() - 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

/**
 * Inventory reports: stock valuation, movement summary, low stock, dead stock.
 * Requirements: Task 54.18
 */
export default function InventoryReport() {
  const [sub, setSub] = useState<SubReport>('stock_valuation')
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
      setError('Failed to load inventory report.')
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
              { value: 'stock_valuation', label: 'Stock Valuation' },
              { value: 'stock_movement_summary', label: 'Movement Summary' },
              { value: 'low_stock', label: 'Low Stock Alert' },
              { value: 'dead_stock', label: 'Dead Stock' },
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
      {loading && <div className="py-16"><Spinner label="Loading inventory report" /></div>}

      {!loading && data && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Inventory report — {sub.replace(/_/g, ' ')}</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Product</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Quantity</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(data.items || []).length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-sm text-gray-500">No data for this period.</td></tr>
              ) : (
                (data.items || []).map((item: any, i: number) => (
                  <tr key={item.product_id || i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">{item.product_name || item.movement_type || '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-700 text-right">{item.quantity ?? item.total_quantity ?? item.current_quantity ?? '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-900 text-right">{item.valuation != null ? fmt(item.valuation) : item.movement_count ?? '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {data.total_valuation != null && (
            <div className="px-4 py-3 bg-blue-50 text-right text-sm font-semibold">
              Total Valuation: {fmt(data.total_valuation)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
