import { useState, useEffect, useCallback, useMemo } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Badge, Spinner, Modal } from '@/components/ui'
import { AddToStockModal } from '@/components/inventory/AddToStockModal'
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

const TH = 'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_C = 'mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/**
 * StockLevels — Task 35 port of frontend/src/pages/inventory/StockLevels.tsx.
 *
 * Stock levels dashboard showing only explicitly stocked items. Uses the
 * unified GET /inventory/stock-items endpoint. ALL logic — fetch, filtering,
 * adjust/threshold submit, the guide toggle, summary counts — copied VERBATIM.
 * Presentation remapped onto the design tokens (FR-2b).
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

  /* Apply search filter across name, part_number, brand, and barcode.
     Also exclude items with zero stock (they still exist in the DB for history). */
  const filtered = useMemo(() => {
    let items = stockItems.filter((s) => s.current_quantity > 0)
    if (!filter.trim()) return items
    const q = filter.toLowerCase()
    return items.filter(
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
        return <Badge variant="neutral" className="bg-purple-soft text-purple">Fluid/Oil</Badge>
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
        <p className="text-[13px] text-muted">
          Current stock levels for explicitly tracked inventory items. Items below minimum threshold are highlighted.
        </p>
        <div className="flex gap-2 items-center">
          <button
            type="button"
            onClick={() => setShowGuide(!showGuide)}
            className="flex items-center gap-1 rounded-ctl border border-accent/30 bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent-soft"
            aria-label="Toggle stock guide"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            Guide
          </button>
          <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>Add to Stock</Button>
          <Button size="sm" variant="ghost" onClick={fetchData}>Refresh</Button>
        </div>
      </div>

      {showGuide && (
        <div className="mb-4 rounded-card border border-accent/30 bg-accent-soft p-4 text-sm text-accent">
          <div className="flex justify-between items-start">
            <div className="space-y-2">
              <p className="font-medium">When to use Adjust Stock vs Add to Stock</p>
              <div className="flex gap-6">
                <div>
                  <p className="font-medium text-text">Use "Adjust Stock"</p>
                  <ul className="mt-1 list-disc list-inside text-xs space-y-0.5 text-accent">
                    <li>Same supplier, same price — just updating quantity</li>
                    <li>Inventory count correction</li>
                    <li>Removing damaged or expired stock</li>
                    <li>Updating min threshold or reorder qty</li>
                  </ul>
                </div>
                <div>
                  <p className="font-medium text-text">Use "Add to Stock"</p>
                  <ul className="mt-1 list-disc list-inside text-xs space-y-0.5 text-accent">
                    <li>Purchase price or sell price has changed</li>
                    <li>Different supplier for this batch</li>
                    <li>New storage location</li>
                    <li>Need to track this batch separately for billing</li>
                  </ul>
                </div>
              </div>
            </div>
            <button type="button" onClick={() => setShowGuide(false)} className="text-muted-2 hover:text-text ml-2 shrink-0" aria-label="Close guide">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>
        </div>
      )}

      {/* Summary cards */}
      {total > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <p className="text-[13px] text-muted">Total Items Tracked</p>
            <p className="mono text-2xl font-semibold text-text">{stockItems.filter((s) => s.current_quantity > 0).length}</p>
          </div>
          <div className="rounded-card border border-warn/30 bg-warn-soft p-4">
            <p className="text-[13px] text-warn">Below Threshold</p>
            <p className="mono text-2xl font-semibold text-warn">{belowThreshold}</p>
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
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">{error}</div>
      )}

      {loading && stockItems.length === 0 && (
        <div className="py-16"><Spinner label="Loading stock levels" /></div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <div className="py-16 text-center">
          <p className="text-muted mb-4">No items in inventory yet. Add catalogue items to start tracking stock.</p>
          <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>Add to Stock</Button>
        </div>
      )}

      {/* Stock levels table */}
      {total > 0 && (
        <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <div className="overflow-x-auto">
          <table className="w-full border-collapse" role="grid">
            <caption className="sr-only">Stock levels</caption>
            <thead>
              <tr>
                <th scope="col" className={TH}>Type</th>
                <th scope="col" className={TH}>Item</th>
                {!selectedBranchId && (
                  <th scope="col" className={TH}>Branch</th>
                )}
                <th scope="col" className={TH}>Part Number</th>
                <th scope="col" className={TH}>Barcode</th>
                <th scope="col" className={TH}>Location</th>
                <th scope="col" className={TH_R}>Cost</th>
                <th scope="col" className={TH_R}>Sell Price</th>
                <th scope="col" className={TH_R}>Stock</th>
                <th scope="col" className={TH_R}>Reserved</th>
                <th scope="col" className={TH_R}>Available</th>
                <th scope="col" className={TH_R}>Min Threshold</th>
                <th scope="col" className={TH_R}>Reorder Qty</th>
                <th scope="col" className={TH_C}>Status</th>
                <th scope="col" className={TH_C}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={selectedBranchId ? 14 : 15} className="px-4 py-12 text-center text-[13px] text-muted">
                    No items match your filter.
                  </td>
                </tr>
              ) : (
                filtered.map((s) => (
                  <tr key={s.id} className={`border-b border-border last:border-b-0 hover:bg-canvas ${s.is_below_threshold ? 'bg-warn-soft/50' : ''}`}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">{typeBadge(s.catalogue_type)}</td>
                    <td className="px-4 py-3 text-sm">
                      <p className="font-medium text-text">{s.item_name}</p>
                      {s.subtitle && <p className="text-xs text-muted">{s.subtitle}</p>}
                    </td>
                    {!selectedBranchId && (
                      <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{s.branch_name ?? 'All'}</td>
                    )}
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{s.part_number || '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{s.barcode || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-[13.5px] text-muted">{s.location || '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">{s.cost_per_unit ? `${s.cost_per_unit.toFixed(2)}${s.catalogue_type === 'fluid' ? '/L' : '/unit'}` : '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">{s.sell_price ? `${s.sell_price.toFixed(2)}${s.catalogue_type === 'fluid' ? '/L' : '/unit'}` : '—'}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right font-medium text-text">{s.current_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">
                      {(s.reserved_quantity || 0) > 0 ? (
                        <span className="text-warn font-medium">{s.reserved_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}</span>
                      ) : (
                        <span className="text-muted-2">—</span>
                      )}
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right font-medium">
                      <span className={(s.available_quantity ?? s.current_quantity) <= s.min_threshold && s.min_threshold > 0 ? 'text-danger' : 'text-ok'}>
                        {s.available_quantity ?? s.current_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}
                      </span>
                    </td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">{s.min_threshold}{s.catalogue_type === 'fluid' ? ' L' : ''}</td>
                    <td className="mono whitespace-nowrap px-4 py-3 text-[13.5px] text-right text-muted">{s.reorder_quantity}{s.catalogue_type === 'fluid' ? ' L' : ''}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <Badge variant={s.is_below_threshold ? 'warn' : 'success'}>
                        {s.is_below_threshold ? 'Low Stock' : 'OK'}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-center">
                      <Button size="sm" variant="ghost" onClick={() => openAdjust(s)}>Adjust Stock</Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          </div>
        </section>
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
            <div className="rounded-ctl border border-border bg-canvas p-3 text-sm">
              <p className="font-medium text-text">{adjustItem.item_name}</p>
              <p className="text-muted">Current stock: <span className="mono font-semibold text-text">{adjustItem.current_quantity}{adjustItem.catalogue_type === 'fluid' ? ' L' : ''}</span>
                {(adjustItem.reserved_quantity || 0) > 0 && <span className="ml-2 text-warn">({adjustItem.reserved_quantity} reserved)</span>}
              </p>
            </div>

            {adjustError && (
              <div className="rounded-ctl bg-danger-soft p-3 text-sm text-danger" role="alert">{adjustError}</div>
            )}

            <div>
              <label className="block text-[12.5px] font-medium text-text mb-1">Quantity Change</label>
              <input
                type="number"
                step="any"
                className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                value={adjustQty}
                onChange={(e) => setAdjustQty(e.target.value)}
                placeholder="e.g. 5 to add, -3 to remove"
              />
              <p className="mt-1 text-xs text-muted">Positive to add stock, negative to remove</p>
            </div>

            <div>
              <label className="block text-[12.5px] font-medium text-text mb-1">Reason</label>
              <select
                className="h-[42px] w-full appearance-none rounded-ctl border border-border bg-card px-3 py-2 text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
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
            <div className="rounded-card border border-border bg-canvas p-3 space-y-3">
              <p className="mono text-xs font-medium text-muted-2 uppercase">Reorder Settings</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12.5px] font-medium text-text mb-1">Min Threshold</label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                    value={adjustMinThreshold}
                    onChange={(e) => setAdjustMinThreshold(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[12.5px] font-medium text-text mb-1">Reorder Qty</label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="mono h-[42px] w-full rounded-ctl border border-border bg-card px-3 py-2 text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                    value={adjustReorderQty}
                    onChange={(e) => setAdjustReorderQty(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {adjustQty && !isNaN(parseFloat(adjustQty)) && parseFloat(adjustQty) !== 0 && (
              <div className="rounded-ctl border border-accent/20 bg-accent-soft p-3 text-sm">
                <p className="text-accent">
                  New stock level: <span className="mono font-semibold">{(adjustItem.current_quantity + parseFloat(adjustQty)).toFixed(3).replace(/\.?0+$/, '')}{adjustItem.catalogue_type === 'fluid' ? ' L' : ''}</span>
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" size="sm" onClick={() => setAdjustItem(null)} disabled={adjustSubmitting}>Cancel</Button>
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
