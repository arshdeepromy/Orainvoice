import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Button, Input, Select, Spinner } from '@/components/ui'

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

const TH = 'mono border-b border-border px-4 py-2 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TH_R = 'mono border-b border-border px-4 py-2 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

/**
 * PurchaseOrders — Task 36 port of frontend/src/pages/inventory/PurchaseOrders.tsx.
 *
 * Purchase order generation form. Select a supplier, add parts with quantities,
 * and generate a PDF purchase order. ALL logic — the parallel fetch from
 * /inventory/suppliers + /inventory/stock, add/remove items, auto-fill low
 * stock, and the PDF generation POST /inventory/purchase-orders (responseType
 * blob) + download — copied VERBATIM. Presentation remapped onto the design
 * tokens (FR-2b) using the PurchaseOrders.html prototype language (page-head
 * eyebrow "Stock", card-wrapped item table). `Button` `secondary`→`ghost`.
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
      setSuppliers(suppRes.data?.suppliers ?? [])
      setParts(stockRes.data?.stock_levels ?? [])
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
    <div className="page page-wide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Stock</div>
          <h1>Purchase orders</h1>
          <p className="sub">Generate a purchase order PDF for a supplier</p>
        </div>
      </div>

      <p className="text-[13px] text-muted mb-4">
        Generate a purchase order PDF for a supplier with parts to reorder.
      </p>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger/30 bg-danger-soft px-4 py-3 text-[13px] text-danger" role="alert">{error}</div>
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
              <label className="text-[12.5px] font-medium text-text">Order Items</label>
              {parts.some((p) => p.is_below_threshold) && (
                <Button size="sm" variant="ghost" onClick={autoFillLowStock}>
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
                <Button size="sm" variant="ghost" onClick={addItem} disabled={!addPartId || !addQuantity}>
                  Add
                </Button>
              </div>
            </div>

            {items.length > 0 && (
              <section className="overflow-hidden rounded-card border border-border bg-card shadow-card">
                <div className="overflow-x-auto">
                <table className="w-full border-collapse" role="grid">
                  <caption className="sr-only">Purchase order items</caption>
                  <thead>
                    <tr>
                      <th scope="col" className={TH}>Part</th>
                      <th scope="col" className={TH}>Part Number</th>
                      <th scope="col" className={TH_R}>Quantity</th>
                      <th scope="col" className={TH_R}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.part_id} className="border-b border-border last:border-b-0 hover:bg-canvas">
                        <td className="whitespace-nowrap px-4 py-2 text-sm font-medium text-text">{item.part_name}</td>
                        <td className="mono whitespace-nowrap px-4 py-2 text-[13.5px] text-muted">{item.part_number || '—'}</td>
                        <td className="mono whitespace-nowrap px-4 py-2 text-sm text-right font-medium text-text">{item.quantity}</td>
                        <td className="whitespace-nowrap px-4 py-2 text-sm text-right">
                          <Button size="sm" variant="danger" onClick={() => removeItem(item.part_id)}>Remove</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </section>
            )}

            {items.length === 0 && (
              <p className="text-[13px] text-muted-2 italic">No items added yet.</p>
            )}
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="po-notes" className="block text-[12.5px] font-medium text-text mb-1">Notes</label>
            <textarea
              id="po-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Additional notes for the purchase order…"
              className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-[13.5px] text-text placeholder:text-muted-2 focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
            />
          </div>

          {formError && <p className="text-[13px] text-danger" role="alert">{formError}</p>}
          {success && (
            <div className="rounded-ctl border border-ok/30 bg-ok-soft px-4 py-3 text-[13px] text-ok" role="status">{success}</div>
          )}

          <Button onClick={handleGenerate} loading={generating} disabled={items.length === 0 || !supplierId}>
            Generate Purchase Order PDF
          </Button>
        </div>
      )}
    </div>
  )
}
