import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Badge, Spinner, AlertBanner } from '../../components/ui'

interface StockItem {
  id: string
  catalogue_item_id: string
  catalogue_type: string
  item_name: string
  part_number: string | null
  brand: string | null
  current_quantity: number
  min_threshold: number
  reorder_quantity: number
  is_below_threshold: boolean
  barcode: string | null
}

interface StockItemListResponse {
  stock_items: StockItem[]
  total: number
}

export default function ReorderAlerts() {
  const [alerts, setAlerts] = useState<StockItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<StockItemListResponse>('/inventory/stock-items', {
        params: { below_threshold_only: true, limit: 500 },
      })
      setAlerts(res.data?.stock_items ?? [])
    } catch {
      setError('Failed to load reorder alerts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAlerts() }, [fetchAlerts])

  function typeBadge(type: string) {
    switch (type) {
      case 'part': return <Badge variant="info">Part</Badge>
      case 'tyre': return <Badge variant="neutral">Tyre</Badge>
      case 'fluid': return <Badge variant="neutral" className="bg-purple-100 text-purple-800 border-purple-300">Fluid/Oil</Badge>
      default: return <Badge variant="neutral">{type}</Badge>
    }
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">
        Items that have fallen below their minimum stock threshold and need reordering.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && alerts.length === 0 && (
        <div className="py-16"><Spinner label="Loading reorder alerts" /></div>
      )}

      {!loading && alerts.length === 0 && !error && (
        <AlertBanner variant="success" title="All stocked up">
          No items are currently below their minimum threshold.
        </AlertBanner>
      )}

      {alerts.length > 0 && (
        <>
          <AlertBanner variant="warning" title={`${alerts.length} item${alerts.length !== 1 ? 's' : ''} need reordering`} className="mb-4">
            The following items have stock levels at or below their minimum threshold.
          </AlertBanner>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Reorder alerts</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Item</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Number</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Current Stock</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Min Threshold</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reorder Qty</th>
                  <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Deficit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {alerts.map((s) => {
                  const deficit = s.min_threshold - s.current_quantity
                  return (
                    <tr key={s.id} className="hover:bg-gray-50 bg-amber-50/50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm">{typeBadge(s.catalogue_type)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{s.item_name}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.part_number || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-red-700">{s.current_quantity}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.min_threshold}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.reorder_quantity}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <Badge variant="error">{deficit > 0 ? `${deficit} short` : 'At threshold'}</Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
