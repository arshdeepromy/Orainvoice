import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Button, Input, Select, Spinner } from '../../components/ui'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Supplier {
  id: string
  name: string
}

interface StockLevel {
  part_id: string
  part_name: string
  part_number: string | null
  current_stock: number
  min_threshold: number
  reorder_quantity: number
  is_below_threshold: boolean
}

interface OrderItem {
  part_id: string
  part_name: string
  part_number: string | null
  quantity: number
}

/**
 * Purchase order generation form. Select a supplier, add parts with quantities,
 * and generate a PDF purchase order.
 *
 * Requirements: 63.3
 */
export default function PurchaseOrders() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [parts, setParts] = useState<StockLevel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [supplierId, setSupplierId] = useState('')
  const [items, setItems] = useState<OrderItem[]>([])
  const [notes, setNotes] = useState('')
  const [generating, setGenerating] = useState(false)
  const [formError, setFormError] = useState('')
  const [success, setSuccess] = useState('')

  /* Add-item state */
  const [addPartId, setAddPartId] = useState('')
  const [addQuantity, setAddQuantity] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [suppRes, stockRes] = await Promise.all([
        apiClient.get<{ suppliers: Supplier[]; total: number }>('/inventory/suppliers'),
        apiClient.get<{ stock_levels: StockLevel[]; total: number }>('/inventory/stock'),
      ])
      setSuppliers(suppRes.data.suppliers)
      setParts(stockRes.data.stock_levels)
    } catch {
      setError('Failed to load suppliers or parts.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const addItem = () => {
    if (!addPartId) return
    const qty = parseInt(addQuantity, 10)
    if (isNaN(qty) || qty <= 0) return

    if (items.some((i) => i.part_id === addPartId)) {
      setItems((prev) => prev.map((i) =>
        i.part_id === addPartId ? { ...i, quantity: i.quantity + qty } : i
      ))
    } else {
      const part = parts.find((p) => p.part_id === addPartId)
      if (!part) return
      setItems((prev) => [...prev, {
        part_id: part.part_id,
        part_name: part.part_name,
        part_number: part.part_number,
        quantity: qty,
      }])
    }
    setAddPartId('')
    setAddQuantity('')
  }

  const removeItem = (partId: string) => {
    setItems((prev) => prev.filter((i) => i.part_id !== partId))
  }

  const autoFillLowStock = () => {
    const lowParts = parts.filter((p) => p.is_below_threshold)
    const newItems: OrderItem[] = lowParts.map((p) => ({
      part_id: p.part_id,
      part_name: p.part_name,
      part_number: p.part_number,
      quantity: p.reorder_quantity,
    }))
    setItems(newItems)
  }

  const handleGenerate = async () => {
    setFormError('')
    setSuccess('')

    if (!supplierId) { setFormError('Please select a supplier.'); return }
    if (items.length === 0) { setFormError('Please add at least one item.'); return }

    setGenerating(true)
    try {
      const res = await apiClient.post('/inventory/purchase-orders', {
        supplier_id: supplierId,
        items: items.map((i) => ({ part_id: i.part_id, quantity: i.quantity })),
        notes: notes.trim() || undefined,
      }, { responseType: 'blob' })

      // Download the PDF
      const blob = new Blob([res.data], { type: 'application/pdf' })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      const supplier = suppliers.find((s) => s.id === supplierId)
      link.download = `PO-${supplier?.name || 'order'}-${new Date().toISOString().slice(0, 10)}.pdf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)

      setSuccess('Purchase order PDF generated and downloaded.')
    } catch {
      setFormError('Failed to generate purchase order.')
    } finally {
      setGenerating(false)
    }
  }

  const supplierOptions = [
    { value: '', label: 'Select a supplier…' },
    ...suppliers.map((s) => ({ value: s.id, label: s.name })),
  ]

  const partOptions = [
    { value: '', label: 'Select a part…' },
    ...parts.map((p) => ({
      value: p.part_id,
      label: `${p.part_name}${p.part_number ? ` (${p.part_number})` : ''} — Stock: ${p.current_stock}`,
    })),
  ]

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">
        Generate a purchase order PDF for a supplier with parts to reorder.
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>
      )}

      {loading && (
        <div className="py-16"><Spinner label="Loading data" /></div>
      )}

      {!loading && (
        <div className="max-w-2xl space-y-6">
          {/* Supplier selection */}
          <Select
            label="Supplier *"
            options={supplierOptions}
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
          />

          {/* Add items */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-gray-700">Order Items</label>
              {parts.some((p) => p.is_below_threshold) && (
                <Button size="sm" variant="secondary" onClick={autoFillLowStock}>
                  Auto-fill low stock
                </Button>
              )}
            </div>

            <div className="flex gap-2 mb-3">
              <div className="flex-1">
                <Select
                  label="Part"
                  options={partOptions}
                  value={addPartId}
                  onChange={(e) => setAddPartId(e.target.value)}
                />
              </div>
              <div className="w-28">
                <Input
                  label="Qty"
                  type="number"
                  placeholder="Qty"
                  value={addQuantity}
                  onChange={(e) => setAddQuantity(e.target.value)}
                />
              </div>
              <div className="flex items-end">
                <Button size="sm" variant="secondary" onClick={addItem} disabled={!addPartId || !addQuantity}>
                  Add
                </Button>
              </div>
            </div>

            {items.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-gray-200">
                <table className="min-w-full divide-y divide-gray-200" role="grid">
                  <caption className="sr-only">Purchase order items</caption>
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part</th>
                      <th scope="col" className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Part Number</th>
                      <th scope="col" className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Quantity</th>
                      <th scope="col" className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {items.map((item) => (
                      <tr key={item.part_id} className="hover:bg-gray-50">
                        <td className="whitespace-nowrap px-4 py-2 text-sm font-medium text-gray-900">{item.part_name}</td>
                        <td className="whitespace-nowrap px-4 py-2 text-sm text-gray-700">{item.part_number || '—'}</td>
                        <td className="whitespace-nowrap px-4 py-2 text-sm text-right tabular-nums font-medium text-gray-900">{item.quantity}</td>
                        <td className="whitespace-nowrap px-4 py-2 text-sm text-right">
                          <Button size="sm" variant="danger" onClick={() => removeItem(item.part_id)}>Remove</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {items.length === 0 && (
              <p className="text-sm text-gray-400 italic">No items added yet.</p>
            )}
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="po-notes" className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <textarea
              id="po-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Additional notes for the purchase order…"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {formError && <p className="text-sm text-red-600" role="alert">{formError}</p>}
          {success && (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700" role="status">{success}</div>
          )}

          <Button onClick={handleGenerate} loading={generating} disabled={items.length === 0 || !supplierId}>
            Generate Purchase Order PDF
          </Button>
        </div>
      )}
    </div>
  )
}
