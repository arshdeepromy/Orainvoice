import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge, Spinner, AlertBanner } from '@/components/ui'

/**
 * ReorderAlerts — Task 35 port of frontend/src/pages/inventory/ReorderAlerts.tsx.
 *
 * Lists items below their minimum stock threshold via
 * GET /inventory/stock-items?below_threshold_only=true. ALL logic copied
 * VERBATIM; presentation remapped onto the design tokens (FR-2b).
 */

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

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_C = 'mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

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
      case 'fluid': return <Badge variant="neutral" className="bg-purple-soft text-purple">Fluid/Oil</Badge>
      default: return <Badge variant="neutral">{type}</Badge>
    }
  }

  return (
    <div>
      <p className="text-[13px] text-muted mb-4">
        Items that have fallen below their minimum stock threshold and need reordering.
      </p>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">{error}</div>
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

          <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <div className="overflow-x-auto">
            <table className="w-full border-collapse" role="grid">
              <caption className="sr-only">Reorder alerts</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Type</th>
                  <th scope="col" className={TH}>Item</th>
                  <th scope="col" className={TH}>Part Number</th>
                  <th scope="col" className={TH_R}>Current Stock</th>
                  <th scope="col" className={TH_R}>Min Threshold</th>
                  <th scope="col" className={TH_R}>Reorder Qty</th>
                  <th scope="col" className={TH_C}>Deficit</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((s) => {
                  const deficit = s.min_threshold - s.current_quantity
                  return (
                    <tr key={s.id} className="border-b border-border last:border-b-0 hover:bg-canvas bg-warn-soft/50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm">{typeBadge(s.catalogue_type)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-[13.5px] font-medium text-text">{s.item_name}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{s.part_number || '—'}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right font-medium text-danger">{s.current_quantity}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">{s.min_threshold}</td>
                      <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">{s.reorder_quantity}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                        <Badge variant="danger">{deficit > 0 ? `${deficit} short` : 'At threshold'}</Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
