import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Badge, Spinner, AlertBanner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ReorderAlert {
  part_id: string
  part_name: string
  part_number: string | null
  current_stock: number
  min_threshold: number
  reorder_quantity: number
}

interface ReorderAlertListResponse {
  alerts: ReorderAlert[]
  total: number
}

/**
 * Reorder alerts view showing parts that have fallen below their minimum stock threshold.
 *
 * Requirements: 62.3
 */
export default function ReorderAlerts() {
  const [data, setData] = useState<ReorderAlertListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<ReorderAlertListResponse>('/inventory/stock/reorder-alerts')
      setData(res.data)
    } catch {
      setError('Failed to load reorder alerts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAlerts() }, [fetchAlerts])

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">
        Parts that have fallen below their minimum stock threshold and need reordering.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && !data && (
        <div className="py-16"><Spinner label="Loading reorder alerts" /></div>
      )}

      {data && data.alerts.length === 0 && (
        <AlertBanner variant="success" title="All stocked up">
          No parts are currently below their minimum threshold.
        </AlertBanner>
      )}

      {data && data.alerts.length > 0 && (
        <>
          <AlertBanner variant="warning" title={`${data.total} part${data.total !== 1 ? 's' : ''} need reordering`} className="mb-4">
            The following parts have stock levels at or below their minimum threshold.
          </AlertBanner>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Reorder alerts</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Number</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Current Stock</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Min Threshold</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reorder Qty</th>
                  <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Deficit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.alerts.map((a) => (
                  <tr key={a.part_id} className="hover:bg-gray-50 bg-amber-50/50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{a.part_name}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{a.part_number || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-red-700">{a.current_stock}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{a.min_threshold}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{a.reorder_quantity}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <Badge variant="error">
                        {a.min_threshold - a.current_stock} short
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
