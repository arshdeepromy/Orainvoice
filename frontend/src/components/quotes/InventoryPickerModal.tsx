/**
 * InventoryPickerModal — allows selecting a stock item from inventory to add as a line item.
 * Includes a "Quick Add Stock" button that opens the AddToStockModal inline.
 * Task 13.2
 */

import { useEffect, useState, useCallback } from 'react'
import apiClient from '../../api/client'
import { Modal } from '../ui'
import { AddToStockModal } from '../inventory/AddToStockModal'

interface StockItem {
  id: string
  catalogue_item_id: string | null
  name: string
  item_name?: string
  sku: string | null
  part_number?: string | null
  category: string | null
  catalogue_type?: string | null
  sell_price: number | string
  gst_inclusive: boolean
  gst_mode?: string | null
  quantity_on_hand: number
  available_quantity?: number
  subtitle?: string | null
  brand?: string | null
  location?: string | null
  supplier_name?: string | null
}

interface InventoryPickerModalProps {
  open: boolean
  onClose: () => void
  onSelect: (item: StockItem) => void
}

export default function InventoryPickerModal({ open, onClose, onSelect }: InventoryPickerModalProps) {
  const [items, setItems] = useState<StockItem[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [addStockOpen, setAddStockOpen] = useState(false)

  const fetchItems = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<{ stock_items?: StockItem[]; items?: StockItem[] }>(
        '/inventory/stock-items',
        { params: { active_only: true }, signal }
      )
      const data = res.data
      setItems(data?.stock_items ?? data?.items ?? [])
    } catch (err) {
      if (!signal?.aborted) {
        setError('Failed to load inventory items')
      }
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    fetchItems(controller.signal)
    return () => controller.abort()
  }, [open, fetchItems])

  const handleAddStockSuccess = useCallback(() => {
    // Refresh the inventory list after adding new stock
    fetchItems()
  }, [fetchItems])

  const filtered = search.trim()
    ? items.filter(i =>
        (i.name ?? i.item_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (i.sku ?? i.part_number ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (i.category ?? i.catalogue_type ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (i.brand ?? '').toLowerCase().includes(search.toLowerCase())
      )
    : items

  return (
    <>
      <Modal open={open} onClose={onClose} title="Add from Inventory">
        <div className="space-y-3">
          {/* Search + Quick Add Stock button */}
          <div className="flex gap-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, SKU, or category…"
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoFocus
            />
            <button
              type="button"
              onClick={() => setAddStockOpen(true)}
              className="shrink-0 rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 transition-colors whitespace-nowrap"
            >
              + Quick Add Stock
            </button>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {loading ? (
            <p className="text-sm text-gray-500 py-4 text-center">Loading…</p>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">
              {search ? 'No items match your search.' : 'No inventory items found.'}
            </p>
          ) : (
            <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100">
              {filtered.map(item => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => { onSelect({ ...item, name: item.name || item.item_name || '', gst_inclusive: item.gst_inclusive ?? (item.gst_mode === 'inclusive') }); onClose() }}
                  className="w-full text-left px-3 py-2 hover:bg-blue-50 flex items-center justify-between min-h-[44px]"
                >
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium text-gray-900">{item.name || item.item_name || 'Unnamed'}</span>
                    {(item.sku || item.part_number) && <span className="ml-2 text-xs text-gray-400">{item.sku || item.part_number}</span>}
                    {item.subtitle && <span className="ml-2 text-xs text-gray-500">{item.subtitle}</span>}
                    <div className="text-xs text-gray-400 mt-0.5">
                      {item.catalogue_type && <span className="capitalize">{item.catalogue_type}</span>}
                      {item.brand && <span> · {item.brand}</span>}
                      {item.location && <span> · 📍 {item.location}</span>}
                      {(item.available_quantity ?? item.quantity_on_hand ?? 0) > 0 && (
                        <span className="ml-1">· {item.available_quantity ?? item.quantity_on_hand} avail.</span>
                      )}
                      {(item.gst_mode === 'inclusive' || item.gst_inclusive) && <span className="ml-1 text-amber-600">(GST inc.)</span>}
                    </div>
                  </div>
                  <div className="text-sm text-gray-700 flex-shrink-0 ml-2">
                    ${Number(item.sell_price ?? 0).toFixed(2)}
                    {(item.gst_inclusive || item.gst_mode === 'inclusive') && <span className="ml-1 text-xs text-gray-400">incl.</span>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </Modal>

      {/* Quick Add Stock Modal — same as inventory page's "Add to Stock" */}
      <AddToStockModal
        isOpen={addStockOpen}
        onClose={() => setAddStockOpen(false)}
        onSuccess={handleAddStockSuccess}
      />
    </>
  )
}
