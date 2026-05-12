/**
 * InventoryPickerModal — allows selecting a stock item from inventory to add as a line item.
 * Task 13.2
 */

import { useEffect, useState } from 'react'
import apiClient from '../../api/client'
import { Modal } from '../ui'

interface StockItem {
  id: string
  catalogue_item_id: string | null
  name: string
  sku: string | null
  category: string | null
  sell_price: number | string
  gst_inclusive: boolean
  quantity_on_hand: number
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

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    async function fetchItems() {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.get<{ stock_items?: StockItem[]; items?: StockItem[] }>(
          '/inventory/stock-items',
          { params: { active_only: true }, signal: controller.signal }
        )
        const data = res.data
        setItems(data?.stock_items ?? data?.items ?? [])
      } catch (err) {
        if (!controller.signal.aborted) {
          setError('Failed to load inventory items')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    fetchItems()
    return () => controller.abort()
  }, [open])

  const filtered = search.trim()
    ? items.filter(i =>
        (i.name ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (i.sku ?? '').toLowerCase().includes(search.toLowerCase()) ||
        (i.category ?? '').toLowerCase().includes(search.toLowerCase())
      )
    : items

  return (
    <Modal open={open} onClose={onClose} title="Add from Inventory">
      <div className="space-y-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, SKU, or category…"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          autoFocus
        />

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
                onClick={() => { onSelect(item); onClose() }}
                className="w-full text-left px-3 py-2 hover:bg-blue-50 flex items-center justify-between min-h-[44px]"
              >
                <div>
                  <span className="text-sm font-medium text-gray-900">{item.name}</span>
                  {item.sku && <span className="ml-2 text-xs text-gray-400">{item.sku}</span>}
                  {item.category && <span className="ml-2 text-xs text-gray-500">({item.category})</span>}
                </div>
                <div className="text-sm text-gray-700 flex-shrink-0 ml-2">
                  ${Number(item.sell_price ?? 0).toFixed(2)}
                  {item.gst_inclusive && <span className="ml-1 text-xs text-gray-400">incl.</span>}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </Modal>
  )
}
