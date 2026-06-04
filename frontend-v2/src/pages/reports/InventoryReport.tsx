import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Select, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

type SubReport = 'stock_valuation' | 'stock_movement_summary' | 'low_stock' | 'dead_stock'

const fmt = (v: number | undefined) => v != null ? v.toLocaleString('en-NZ', { minimumFractionDigits: 2 }) : '0.00'

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
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

      {error && <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">{error}</div>}
      {loading && <div className="py-16"><Spinner label="Loading inventory report" /></div>}

      {!loading && data && (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full" role="grid">
            <caption className="sr-only">Inventory report — {sub.replace(/_/g, ' ')}</caption>
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Product</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Quantity</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Value</th>
              </tr>
            </thead>
            <tbody>
              {(data.items || []).length === 0 ? (
                <tr><td colSpan={3} className="px-4 py-12 text-center text-sm text-muted">No data for this period.</td></tr>
              ) : (
                (data.items || []).map((item: any, i: number) => (
                  <tr key={item.product_id || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className="px-4 py-3 text-sm text-text">{item.product_name || item.movement_type || '-'}</td>
                    <td className="px-4 py-3 text-sm text-muted text-right mono">{item.quantity ?? item.total_quantity ?? item.current_quantity ?? '-'}</td>
                    <td className="px-4 py-3 text-sm text-text text-right mono">{item.valuation != null ? fmt(item.valuation) : item.movement_count ?? '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {data.total_valuation != null && (
            <div className="px-4 py-3 bg-accent-soft text-right text-sm font-semibold text-text mono">
              Total Valuation: {fmt(data.total_valuation)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
