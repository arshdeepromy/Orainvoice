import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal, Input, Select } from '@/components/ui'

interface Supplier { id: string; name: string }
interface Product { id: string; name: string; sku: string | null; cost_price: number }

interface POLine {
  id: string
  product_id: string
  description: string | null
  quantity_ordered: number
  quantity_received: number
  unit_cost: number
  line_total: number
}

interface PurchaseOrder {
  id: string
  po_number: string
  supplier_id: string
  status: string
  expected_delivery: string | null
  total_amount: number
  notes: string | null
  created_at: string
  lines: POLine[]
}

interface NewLine { product_id: string; description: string; quantity: number; unit_cost: number }

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'sent', label: 'Sent' },
  { value: 'partial', label: 'Partially Received' },
  { value: 'received', label: 'Received' },
  { value: 'cancelled', label: 'Cancelled' },
]

function statusBadge(status: string) {
  const map: Record<string, 'info' | 'warning' | 'success' | 'error' | 'neutral'> = {
    draft: 'neutral', sent: 'info', partial: 'warning', received: 'success', cancelled: 'error',
  }
  const labels: Record<string, string> = {
    draft: 'Draft', sent: 'Sent', partial: 'Partial', received: 'Received', cancelled: 'Cancelled',
  }
  return <Badge variant={map[status] || 'neutral'}>{labels[status] || status}</Badge>
}

function formatNZD(amount: number) {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

export default function POList() {
  const navigate = useNavigate()
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const pageSize = 20

  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [supplierMap, setSupplierMap] = useState<Record<string, string>>({})

  // Create modal
  const [showCreate, setShowCreate] = useState(false)
  const [createSupplierId, setCreateSupplierId] = useState('')
  const [createExpectedDelivery, setCreateExpectedDelivery] = useState('')
  const [createNotes, setCreateNotes] = useState('')
  const [createLines, setCreateLines] = useState<NewLine[]>([])
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState('')

  // Add line state
  const [addProductId, setAddProductId] = useState('')
  const [addQty, setAddQty] = useState('')
  const [addCost, setAddCost] = useState('')

  const fetchOrders = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { page: String(page), page_size: String(pageSize) }
      if (statusFilter) params.status = statusFilter
      const res = await apiClient.get('/api/v2/purchase-orders', { params })
      const data = res.data
      setOrders(data.purchase_orders || [])
      setTotal(data.total || 0)
    } catch { setOrders([]) }
    finally { setLoading(false) }
  }, [page, statusFilter])

  const fetchMeta = useCallback(async () => {
    try {
      const [suppRes, prodRes] = await Promise.all([
        apiClient.get('/api/v2/suppliers'),
        apiClient.get('/api/v2/products', { params: { page_size: 500 } }),
      ])
      const supps: Supplier[] = suppRes.data.suppliers || suppRes.data || []
      setSuppliers(supps)
      const map: Record<string, string> = {}
      supps.forEach(s => { map[s.id] = s.name })
      setSupplierMap(map)
      const prods = prodRes.data.products || prodRes.data || []
      setProducts(prods)
    } catch { /* non-blocking */ }
  }, [])

  useEffect(() => { fetchOrders() }, [fetchOrders])
  useEffect(() => { fetchMeta() }, [fetchMeta])

  const totalPages = Math.ceil(total / pageSize)

  const openCreate = () => {
    setCreateSupplierId('')
    setCreateExpectedDelivery('')
    setCreateNotes('')
    setCreateLines([])
    setCreateError('')
    setAddProductId('')
    setAddQty('')
    setAddCost('')
    setShowCreate(true)
  }

  const addLine = () => {
    if (!addProductId) return
    const qty = parseFloat(addQty)
    const cost = parseFloat(addCost)
    if (isNaN(qty) || qty <= 0 || isNaN(cost) || cost < 0) return
    const prod = products.find(p => p.id === addProductId)
    setCreateLines(prev => [...prev, {
      product_id: addProductId,
      description: prod?.name || '',
      quantity: qty,
      unit_cost: cost,
    }])
    setAddProductId('')
    setAddQty('')
    setAddCost('')
  }

  const removeLine = (idx: number) => {
    setCreateLines(prev => prev.filter((_, i) => i !== idx))
  }

  const handleCreate = async () => {
    if (!createSupplierId) { setCreateError('Select a supplier.'); return }
    if (createLines.length === 0) { setCreateError('Add at least one line item.'); return }
    setCreateSaving(true)
    setCreateError('')
    try {
      await apiClient.post('/api/v2/purchase-orders', {
        supplier_id: createSupplierId,
        expected_delivery: createExpectedDelivery || null,
        notes: createNotes.trim() || null,
        lines: createLines.map(l => ({
          product_id: l.product_id,
          description: l.description,
          quantity_ordered: l.quantity,
          unit_cost: l.unit_cost,
        })),
      })
      setShowCreate(false)
      fetchOrders()
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || 'Failed to create purchase order.')
    } finally { setCreateSaving(false) }
  }

  // Auto-fill cost when product selected
  const handleProductSelect = (productId: string) => {
    setAddProductId(productId)
    const prod = products.find(p => p.id === productId)
    if (prod && prod.cost_price) setAddCost(String(prod.cost_price))
  }

  const lineTotal = createLines.reduce((sum, l) => sum + l.quantity * l.unit_cost, 0)

  const supplierOptions = [{ value: '', label: 'Select supplier…' }, ...suppliers.map(s => ({ value: s.id, label: s.name }))]
  const productOptions = [{ value: '', label: 'Select product…' }, ...products.map(p => ({ value: p.id, label: `${p.name}${p.sku ? ` (${p.sku})` : ''}` }))]

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Purchase Orders</h1>
        <Button onClick={openCreate}>+ New Purchase Order</Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <div className="w-48">
          <Select label="Status" options={STATUS_OPTIONS} value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1) }} />
        </div>
      </div>

      {loading ? (
        <div className="py-16 text-center"><Spinner label="Loading purchase orders" /></div>
      ) : orders.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
          <p className="text-gray-500">No purchase orders found.</p>
          <Button className="mt-4" onClick={openCreate}>Create your first PO</Button>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">PO Number</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Supplier</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Expected Delivery</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {orders.map(po => (
                  <tr key={po.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => navigate(`/purchase-orders/${po.id}`)}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-blue-600">{po.po_number}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900">{supplierMap[po.supplier_id] || po.supplier_id.slice(0, 8)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">{statusBadge(po.status)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{po.expected_delivery || '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-right font-medium text-gray-900">{formatNZD(Number(po.total_amount))}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">{new Date(po.created_at).toLocaleDateString('en-NZ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">{total} purchase order{total !== 1 ? 's' : ''}</p>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                <span className="flex items-center text-sm text-gray-600">Page {page} of {totalPages}</span>
                <Button size="sm" variant="secondary" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Create PO Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="New Purchase Order">
        <div className="space-y-4">
          <Select label="Supplier *" options={supplierOptions} value={createSupplierId}
            onChange={e => setCreateSupplierId(e.target.value)} />
          <Input label="Expected Delivery" type="date" value={createExpectedDelivery}
            onChange={e => setCreateExpectedDelivery(e.target.value)} />

          {/* Line items */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Line Items</label>
            <div className="flex gap-2 mb-2">
              <div className="flex-1">
                <Select label="Product" options={productOptions} value={addProductId}
                  onChange={e => handleProductSelect(e.target.value)} />
              </div>
              <div className="w-20">
                <Input label="Qty" type="number" min="1" value={addQty}
                  onChange={e => setAddQty(e.target.value)} />
              </div>
              <div className="w-28">
                <Input label="Unit Cost" type="number" min="0" step="0.01" value={addCost}
                  onChange={e => setAddCost(e.target.value)} />
              </div>
              <div className="flex items-end">
                <Button size="sm" variant="secondary" onClick={addLine} disabled={!addProductId || !addQty || !addCost}>Add</Button>
              </div>
            </div>

            {createLines.length > 0 && (
              <div className="rounded border border-gray-200 overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Product</th>
                      <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">Qty</th>
                      <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">Unit Cost</th>
                      <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">Total</th>
                      <th className="px-3 py-2 w-10"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {createLines.map((l, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2 text-gray-900">{l.description}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{l.quantity}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatNZD(l.unit_cost)}</td>
                        <td className="px-3 py-2 text-right tabular-nums font-medium">{formatNZD(l.quantity * l.unit_cost)}</td>
                        <td className="px-3 py-2">
                          <button type="button" onClick={() => removeLine(i)} className="text-red-500 hover:text-red-700 text-xs">✕</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-gray-50">
                    <tr>
                      <td colSpan={3} className="px-3 py-2 text-right text-sm font-medium text-gray-700">Total:</td>
                      <td className="px-3 py-2 text-right text-sm font-semibold text-gray-900 tabular-nums">{formatNZD(lineTotal)}</td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
            {createLines.length === 0 && <p className="text-sm text-gray-400 italic">No items added yet.</p>}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <textarea value={createNotes} onChange={e => setCreateNotes(e.target.value)} rows={2}
              placeholder="Optional notes…"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          {createError && <p className="text-sm text-red-600">{createError}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} loading={createSaving}>Create Purchase Order</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
