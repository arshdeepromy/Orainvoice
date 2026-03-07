import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Badge, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StockLevel {
  part_id: string
  part_name: string
  part_number: string | null
  current_stock: number
  min_threshold: number
  reorder_quantity: number
  is_below_threshold: boolean
}

interface StockMovement {
  id: string
  part_id: string
  quantity_change: number
  reason: string
  reference_id: string | null
  recorded_by: string
  created_at: string
}

interface StockReportResponse {
  current_levels: StockLevel[]
  below_threshold: StockLevel[]
  movement_history: StockMovement[]
}

/**
 * Stock levels dashboard showing current levels, min threshold, reorder quantity,
 * and recent stock movement history.
 *
 * Requirements: 62.1, 62.4
 */
export default function StockLevels() {
  const [report, setReport] = useState<StockReportResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')

  const fetchReport = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<StockReportResponse>('/inventory/stock/report')
      setReport(res.data)
    } catch {
      setError('Failed to load stock report.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchReport() }, [fetchReport])

  const filtered = report?.current_levels.filter((s) => {
    if (!filter.trim()) return true
    const q = filter.toLowerCase()
    return (
      s.part_name.toLowerCase().includes(q) ||
      (s.part_number && s.part_number.toLowerCase().includes(q))
    )
  }) ?? []

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Current stock levels for all parts. Parts below minimum threshold are highlighted.
        </p>
        <Button size="sm" variant="secondary" onClick={fetchReport}>Refresh</Button>
      </div>

      {/* Summary cards */}
      {report && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Total Parts Tracked</p>
            <p className="text-2xl font-semibold text-gray-900">{report.current_levels.length}</p>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm text-amber-700">Below Threshold</p>
            <p className="text-2xl font-semibold text-amber-800">{report.below_threshold.length}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Recent Movements</p>
            <p className="text-2xl font-semibold text-gray-900">{report.movement_history.length}</p>
          </div>
        </div>
      )}

      {/* Filter */}
      <div className="mb-4 max-w-sm">
        <Input
          label="Filter parts"
          placeholder="Search by name or part number…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter stock levels"
        />
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !report && (
        <div className="py-16"><Spinner label="Loading stock levels" /></div>
      )}

      {report && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Stock levels</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Number</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Current Stock</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Min Threshold</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reorder Qty</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                    {filter ? 'No parts match your filter.' : 'No parts in inventory yet.'}
                  </td>
                </tr>
              ) : (
                filtered.map((s) => (
                  <tr key={s.part_id} className={`hover:bg-gray-50 ${s.is_below_threshold ? 'bg-amber-50/50' : ''}`}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{s.part_name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.part_number || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-gray-900">{s.current_stock}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.min_threshold}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.reorder_quantity}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <Badge variant={s.is_below_threshold ? 'warning' : 'success'}>
                        {s.is_below_threshold ? 'Low Stock' : 'OK'}
                      </Badge>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent movements */}
      {report && report.movement_history.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-medium text-gray-900 mb-3">Recent Stock Movements</h3>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Recent stock movements</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Change</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {report.movement_history.slice(0, 20).map((m) => (
                  <tr key={m.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {new Date(m.created_at).toLocaleDateString('en-NZ')}
                    </td>
                    <td className={`whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium ${m.quantity_change > 0 ? 'text-green-700' : 'text-red-700'}`}>
                      {m.quantity_change > 0 ? '+' : ''}{m.quantity_change}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">{m.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
