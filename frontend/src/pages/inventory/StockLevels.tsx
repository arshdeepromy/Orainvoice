import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Badge, Spinner, Modal } from '../../components/ui'
import { AddToStockModal } from '../../components/inventory/AddToStockModal'
import { useBranch } from '@/contexts/BranchContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StockItem {
  id: string
  catalogue_item_id: string
  catalogue_type: string
  item_name: string
  part_number: string | null
  brand: string | null
  subtitle: string | null
  current_quantity: number
  reserved_quantity: number
  available_quantity: number
  min_threshold: number
  reorder_quantity: number
  is_below_threshold: boolean
  supplier_id: string | null
  supplier_name: string | null
  barcode: string | null
  location: string | null
  cost_per_unit: number | null
  sell_price: number | null
  created_at: string
  branch_name: string | null
  branch_id: string | null
}

interface StockItemListResponse {
  stock_items: StockItem[]
  total: number
}

/**
 * Stock levels dashboard showing only explicitly stocked items.
 * Uses the unified GET /inventory/stock-items endpoint.
 *
 * Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 7.2, 7.3
 */
export default function StockLevels() {
  const { selectedBranchId } = useBranch()
  const [stockItems, setStockItems] = useState<StockItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [adjustItem, setAdjustItem] = useState<StockItem | null>(null)
  const [adjustQty, setAdjustQty] = useState('')
  const [adjustReason, setAdjustReason] = useState('')
  const [adjustSubmitting, setAdjustSubmitting] = useState(false)
  const [adjustError, setAdjustError] = useState('')
  const [adjustMinThreshold, setAdjustMinThreshold] = useState('')
  const [adjustReorderQty, setAdjustReorderQty] = useState('')
  const [showGuide, setShowGuide] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<StockItemListResponse>('/inventory/stock-items')
      setStockItems(res.data?.stock_items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch {
      setError('Failed to load stock data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  /* Apply search filter across name, part_number, brand, and barcode */
  const filtered = useMemo(() => {
    if (!filter.trim()) return stockItems
    const q = filter.toLowerCase()
    return stockItems.filter(
      (s) =>
        s.item_name.toLowerCase().includes(q) ||
        (s.part_number && s.part_number.toLowerCase().includes(q)) ||
        (s.brand && s.brand.toLowerCase().includes(q)) ||
        (s.barcode && s.barcode.toLowerCase().includes(q)) ||
        (s.location && s.location.toLowerCase().includes(q))
    )
  }, [stockItems, filter])

  /* Summary counts */
  const belowThreshold = stockItems.filter((s) => s.is_below_threshold).length

  /* Catalogue type badge helper */
  function typeBadge(type: string) {
    switch (type) {
      case 'part':
        return <Badge variant="info">Part</Badge>
      case 'tyre':
        return <Badge variant="neutral">Tyre</Badge>
      case 'fluid':
        return <Badge variant="neutral" className="bg-purple-100 text-purple-800 border-purple-300">Fluid/Oil</Badge>
      default:
        return <Badge variant="neutral">{type}</Badge>
    }
  }

  const handleModalSuccess = () => {
    setModalOpen(false)
    fetchData()
  }

  const handleAdjustSubmit = async () => {
    if (!adjustItem) return
    const qty = parseFloat(adjustQty)
    const hasQtyChange = adjustQty && !isNaN(qty) && qty !== 0
    if (hasQtyChange && !adjustReason.trim()) { setAdjustError('Please select a reason for stock adjustment'); return }

    setAdjustSubmitting(true)
    setAdjustError('')
    try {
      // Save threshold changes via PUT
      const newMin = parseFloat(adjustMinThreshold) || 0
      const newReorder = parseFloat(adjustReorderQty) || 0
      if (newMin !== adjustItem.min_threshold || newReorder !== adjustItem.reorder_quantity) {
        await apiClient.put(`/inventory/stock-items/${adjustItem.id}`, {
          min_threshold: newMin,
          reorder_quantity: newReorder,
        })
      }

      // Adjust stock quantity if changed
      if (hasQtyChange) {
        await apiClient.post(`/inventory/stock-items/${adjustItem.id}/adjust`, {
          quantity_change: qty,
          reason: adjustReason,
        })
      }

      setAdjustItem(null)
      setAdjustQty('')
      setAdjustReason('')
      fetchData()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setAdjustError(axiosErr?.response?.data?.detail || 'Failed to save changes')
    } finally { setAdjustSubmitting(false) }
  }

  const openAdjust = (item: StockItem) => {
    setAdjustItem(item)
    setAdjustQty('')
    setAdjustReason('')
    setAdjustError('')
    setAdjustMinThreshold(String(item.min_threshold))
    setAdjustReorderQty(String(item.reorder_quantity))
  }

  const isEmpty = !loading && stockItems.length === 0 && !error

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
        <p className="text-sm text-gray-500">
          Current stock levels for explicitly tracked inventory items. Items below minimum threshold are highlighted.
        </p>
        <div className="flex gap-2 items-center">
          <button
            type="button"
            onClick={() => setShowGuide(!showGuide)}
            className="flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
            aria-label="Toggle stock guide"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            Guide
          </button>
          <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>Add to Stock</Button>
          <Button size="sm" variant="secondary" onClick={fetchData}>Refresh</Button>
        </div>
      </div>

      {showGuide && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800">
          <div className="flex justify-between items-start">
            <div className="space-y-2">
              <p className="font-medium">When to use Adjust Stock vs Add to Stock</p>
              <div className="flex gap-6">
                <div>
                  <p className="font-medium text-blue-900">Use "Adjust Stock"</p>
                  <ul className="mt-1 list-disc list-inside text-xs space-y-0.5 text-blue-700">
                    <li>Same supplier, same price — just updating quantity</li>
                    <li>Inventory count correction</li>
                    <li>Removing damaged or expired stock</li>
                    <li>Updating min threshold or reorder qty</li>
                  </ul>
                </div>
                <div>
                  <p className="font-medium text-blue-900">Use "Add to Stock"</p>
                  <ul className="mt-1 list-disc list-inside text-xs space-y-0.5 text-blue-700">
                    <li>Purchase price or sell price has changed</li>
                    <li>Different supplier for this batch</li>
                    <li>New storage location</li>
                    <li>Need to track this batch separately for billing</li>
                  </ul>
                </div>
              </div>
            </div>
            <button type="button" onClick={() => setShowGuide(false)} className="text-blue-400 hover:text-blue-600 ml-2 shrink-0" aria-label="Close guide">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>
        </div>
      )}

      {/* Summary cards */}
      {total > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Total Items Tracked</p>
            <p className="text-2xl font-semibold text-gray-900">{total}</p>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm text-amber-700">Below Threshold</p>
            <p className="text-2xl font-semibold text-amber-800">{belowThreshold}</p>
          </div>
        </div>
      )}

      {/* Search filter */}
      {total > 0 && (
        <div className="mb-4 max-w-sm">
          <Input
            label="Filter items"
            placeholder="Search by name, part number, brand, or barcode…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            aria-label="Filter stock levels"
          />
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && stockItems.length === 0 && (
        <div className="py-16"><Spinner label="Loading stock levels" /></div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <div className="py-16 text-center">
          <p className="text-gray-500 mb-4">No items in inventory yet. Add catalogue items to start tracking stock.</p>
          <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>Add to Stock</Button>
        </div>
      )}

      {/* Stock levels table */}
      {total > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200" role="grid">
            <caption className="sr-only">Stock levels</caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Item</th>
                {!selectedBranchId && (
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Branch</th>
                )}
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Number</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Barcode</th>
                <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Location</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Cost</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Sell Price</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Stock</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reserved</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Available</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Min Threshold</th>
                <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Reorder Qty</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                <th scope="col" className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={selectedBranchId ? 14 : 15} className="px-4 py-12 text-center text-sm text-gray-500">
                    No items match your filter.
                  </td>
                </tr>
              ) : (
                filtered.map((s) => (
                  <tr key={s.id} className={`hover:bg-gray-50 ${s.is_below_threshold ? 'bg-amber-50/50' : ''}`}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">{typeBadge(s.catalogue_type)}</td>
                    <td className="px-4 py-3 text-sm">
                      <p className="font-medium text-gray-900">{s.item_name}</p>
                      {s.subtitle && <p className="text-xs text-gray-500">{s.subtitle}</p>}
                    </td>
                    {!selectedBranchId && (
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.branch_name ?? 'All'}</td>
                    )}
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.part_number || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.barcode || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{s.location || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.cost_per_unit ? `$${s.cost_per_unit.toFixed(2)}${s.catalogue_type === 'fluid' ? '/L' : '/unit'}` : '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.sell_price ? `$${s.sell_price.toFixed(2)}${s.catalogue_type === 'fluid' ? '/L' : '/unit'}` : '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium text-gray-900">{s.current_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">
                      {(s.reserved_quantity || 0) > 0 ? (
                        <span className="text-orange-600 font-medium">{s.reserved_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}</span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums font-medium">
                      <span className={(s.available_quantity ?? s.current_quantity) <= s.min_threshold && s.min_threshold > 0 ? 'text-red-600' : 'text-green-700'}>
                        {s.available_quantity ?? s.current_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.min_threshold}{s.catalogue_type === 'fluid' ? ' L' : ''}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right tabular-nums text-gray-700">{s.reorder_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <Badge variant={s.is_below_threshold ? 'warning' : 'success'}>
                        {s.is_below_threshold ? 'Low Stock' : 'OK'}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <Button size="sm" variant="secondary" onClick={() => openAdjust(s)}>Adjust Stock</Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Add to Stock Modal */}
      <AddToStockModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={handleModalSuccess}
      />

      {/* Adjust Stock Modal */}
      <Modal open={!!adjustItem} onClose={() => setAdjustItem(null)} title="Adjust Stock">
        {adjustItem && (
          <div className="space-y-4">
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
              <p className="font-medium text-gray-900">{adjustItem.item_name}</p>
              <p className="text-gray-500">Current stock: <span className="font-semibold text-gray-900">{adjustItem.current_quantity}{adjustItem.catalogue_type === 'fluid' ? ' L' : ''}</span>
                {(adjustItem.reserved_quantity || 0) > 0 && <span className="ml-2 text-orange-600">({adjustItem.reserved_quantity} reserved)</span>}
              </p>
            </div>

            {adjustError && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">{adjustError}</div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Quantity Change</label>
              <input
                type="number"
                step="any"
                className="h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                value={adjustQty}
                onChange={(e) => setAdjustQty(e.target.value)}
                placeholder="e.g. 5 to add, -3 to remove"
              />
              <p className="mt-1 text-xs text-gray-500">Positive to add stock, negative to remove</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Reason</label>
              <select
                className="h-[42px] w-full appearance-none rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                value={adjustReason}
                onChange={(e) => setAdjustReason(e.target.value)}
              >
                <option value="" disabled>Select a reason…</option>
                <option value="Purchase Order received">Purchase Order received</option>
                <option value="Stocktake correction">Stocktake correction</option>
                <option value="Damaged / write-off">Damaged / write-off</option>
                <option value="Transfer in">Transfer in</option>
                <option value="Transfer out">Transfer out</option>
                <option value="Return to supplier">Return to supplier</option>
                <option value="Customer return">Customer return</option>
                <option value="Other">Other</option>
              </select>
            </div>

            {/* Threshold settings */}
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-3">
              <p className="text-xs font-medium text-gray-500 uppercase">Reorder Settings</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Min Threshold</label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    value={adjustMinThreshold}
                    onChange={(e) => setAdjustMinThreshold(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Reorder Qty</label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    value={adjustReorderQty}
                    onChange={(e) => setAdjustReorderQty(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {adjustQty && !isNaN(parseFloat(adjustQty)) && parseFloat(adjustQty) !== 0 && (
              <div className="rounded-md border border-blue-100 bg-blue-50 p-3 text-sm">
                <p className="text-blue-800">
                  New stock level: <span className="font-semibold">{(adjustItem.current_quantity + parseFloat(adjustQty)).toFixed(3).replace(/\.?0+$/, '')}{adjustItem.catalogue_type === 'fluid' ? ' L' : ''}</span>
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setAdjustItem(null)} disabled={adjustSubmitting}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={handleAdjustSubmit} loading={adjustSubmitting} disabled={adjustSubmitting}>
                {adjustSubmitting ? 'Saving…' : 'Save Changes'}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
