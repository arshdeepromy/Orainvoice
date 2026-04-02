import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { Button, Badge, Spinner, Modal, Input, Select } from '@/components/ui'
import { useBranch } from '@/contexts/BranchContext'

interface Supplier { id: string; name: string; contact_name?: string | null; email?: string | null; phone?: string | null; address?: string | null }
interface CataloguePart {
  id: string; name: string; part_number: string | null; brand: string | null
  default_price: string; part_type: string; current_stock?: number
}

// Unified item for the product search (covers both products and catalogue parts)
interface SearchItem {
  id: string; name: string; sku: string | null; cost_price: number
  source: 'product' | 'catalogue'; stock?: number
}

interface POLine {
  id: string
  product_id: string | null
  catalogue_item_id?: string | null
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
  branch_id?: string | null
}

interface NewLine {
  product_id: string | null
  catalogue_item_id: string | null
  description: string
  quantity: number
  unit_cost: number
}

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
  const { branches: branchList, selectedBranchId } = useBranch()
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const pageSize = 20

  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [searchItems, setSearchItems] = useState<SearchItem[]>([])
  const [supplierMap, setSupplierMap] = useState<Record<string, string>>({})

  // Create modal
  const [showCreate, setShowCreate] = useState(false)
  const [createSupplierId, setCreateSupplierId] = useState('')
  const [createSupplierName, setCreateSupplierName] = useState('')
  const [createExpectedDelivery, setCreateExpectedDelivery] = useState('')
  const [createNotes, setCreateNotes] = useState('')
  const [createLines, setCreateLines] = useState<NewLine[]>([])
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState('')

  // Supplier search state
  const [supplierQuery, setSupplierQuery] = useState('')
  const [supplierDropdownOpen, setSupplierDropdownOpen] = useState(false)
  const supplierRef = useRef<HTMLDivElement>(null)

  // Product/part search state
  const [productQuery, setProductQuery] = useState('')
  const [productDropdownOpen, setProductDropdownOpen] = useState(false)
  const [selectedItem, setSelectedItem] = useState<SearchItem | null>(null)
  const productRef = useRef<HTMLDivElement>(null)
  const [addQty, setAddQty] = useState('')
  const [addCost, setAddCost] = useState('')

  // Add supplier modal
  const [showAddSupplier, setShowAddSupplier] = useState(false)
  const [newSupplier, setNewSupplier] = useState({ name: '', contact_name: '', email: '', phone: '', address: '' })
  const [addSupplierSaving, setAddSupplierSaving] = useState(false)
  const [addSupplierError, setAddSupplierError] = useState('')

  // Add part modal
  const [showAddPart, setShowAddPart] = useState(false)
  const [newPart, setNewPart] = useState({ name: '', part_number: '', brand: '', default_price: '', description: '' })
  const [addPartSaving, setAddPartSaving] = useState(false)
  const [addPartError, setAddPartError] = useState('')

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
      const [suppRes, partsRes] = await Promise.all([
        apiClient.get('/api/v2/suppliers'),
        apiClient.get('/catalogue/parts', { params: { limit: 500 } }),
      ])
      const supps: Supplier[] = suppRes.data.suppliers || suppRes.data || []
      setSuppliers(supps)
      const map: Record<string, string> = {}
      supps.forEach(s => { map[s.id] = s.name })
      setSupplierMap(map)

      // Build unified search items from catalogue parts
      const parts: CataloguePart[] = partsRes.data.parts || []
      const items: SearchItem[] = parts.map(p => ({
        id: p.id,
        name: p.name,
        sku: p.part_number,
        cost_price: Number(p.default_price) || 0,
        source: 'catalogue' as const,
      }))
      setSearchItems(items)
    } catch (err) {
      // Fallback for suppliers
      try {
        const suppRes = await apiClient.get('/inventory/suppliers')
        const supps: Supplier[] = suppRes.data.suppliers || []
        setSuppliers(supps)
        const map: Record<string, string> = {}
        supps.forEach(s => { map[s.id] = s.name })
        setSupplierMap(map)
      } catch { /* non-blocking */ }
    }
  }, [])

  useEffect(() => { fetchOrders() }, [fetchOrders])
  useEffect(() => { fetchMeta() }, [fetchMeta])

  // Close supplier dropdown on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (supplierRef.current && !supplierRef.current.contains(e.target as Node)) {
        setSupplierDropdownOpen(false)
      }
      if (productRef.current && !productRef.current.contains(e.target as Node)) {
        setProductDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const totalPages = Math.ceil(total / pageSize)

  const openCreate = () => {
    setCreateSupplierId('')
    setCreateSupplierName('')
    setSupplierQuery('')
    setCreateExpectedDelivery('')
    setCreateNotes('')
    setCreateLines([])
    setCreateError('')
    setSelectedItem(null)
    setProductQuery('')
    setAddQty('')
    setAddCost('')
    setShowCreate(true)
  }

  // Supplier search helpers — show all when query empty, filter when typing
  const filteredSuppliers = supplierQuery.trim() === ''
    ? suppliers
    : suppliers.filter(s => s.name.toLowerCase().includes(supplierQuery.toLowerCase()))

  const selectSupplier = (s: Supplier) => {
    setCreateSupplierId(s.id)
    setCreateSupplierName(s.name)
    setSupplierQuery(s.name)
    setSupplierDropdownOpen(false)
  }

  const clearSupplier = () => {
    setCreateSupplierId('')
    setCreateSupplierName('')
    setSupplierQuery('')
  }

  const openAddSupplier = () => {
    setNewSupplier({ name: supplierQuery.trim(), contact_name: '', email: '', phone: '', address: '' })
    setAddSupplierError('')
    setShowAddSupplier(true)
  }

  const handleAddSupplier = async () => {
    if (!newSupplier.name.trim()) { setAddSupplierError('Supplier name is required.'); return }
    setAddSupplierSaving(true)
    setAddSupplierError('')
    try {
      const body: Record<string, string> = { name: newSupplier.name.trim() }
      if (newSupplier.contact_name.trim()) body.contact_name = newSupplier.contact_name.trim()
      if (newSupplier.email.trim()) body.email = newSupplier.email.trim()
      if (newSupplier.phone.trim()) body.phone = newSupplier.phone.trim()
      if (newSupplier.address.trim()) body.address = newSupplier.address.trim()
      const res = await apiClient.post('/inventory/suppliers', body)
      const created: Supplier = res.data.supplier || res.data
      // Add to local list and select it
      setSuppliers(prev => [...prev, created])
      setSupplierMap(prev => ({ ...prev, [created.id]: created.name }))
      selectSupplier(created)
      setShowAddSupplier(false)
    } catch (err: any) {
      setAddSupplierError(err?.response?.data?.detail || 'Failed to create supplier.')
    } finally { setAddSupplierSaving(false) }
  }

  const addLine = () => {
    if (!selectedItem) return
    const qty = parseFloat(addQty)
    const cost = parseFloat(addCost)
    if (isNaN(qty) || qty <= 0 || isNaN(cost) || cost < 0) return
    setCreateLines(prev => [...prev, {
      product_id: selectedItem.source === 'product' ? selectedItem.id : null,
      catalogue_item_id: selectedItem.source === 'catalogue' ? selectedItem.id : null,
      description: selectedItem.name,
      quantity: qty,
      unit_cost: cost,
    }])
    setSelectedItem(null)
    setProductQuery('')
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
        branch_id: selectedBranchId || undefined,
        expected_delivery: createExpectedDelivery || null,
        notes: createNotes.trim() || null,
        lines: createLines.map(l => ({
          product_id: l.product_id || null,
          catalogue_item_id: l.catalogue_item_id || null,
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

  // Product/part search helpers
  const filteredItems = productQuery.trim() === ''
    ? searchItems
    : searchItems.filter(i =>
        i.name.toLowerCase().includes(productQuery.toLowerCase()) ||
        (i.sku && i.sku.toLowerCase().includes(productQuery.toLowerCase()))
      )

  const selectItem = (item: SearchItem) => {
    setSelectedItem(item)
    setProductQuery(item.name)
    setProductDropdownOpen(false)
    if (item.cost_price) setAddCost(String(item.cost_price))
  }

  const clearItem = () => {
    setSelectedItem(null)
    setProductQuery('')
    setAddCost('')
  }

  const openAddPart = () => {
    setNewPart({ name: productQuery.trim(), part_number: '', brand: '', default_price: '', description: '' })
    setAddPartError('')
    setShowAddPart(true)
  }

  const handleAddPart = async () => {
    if (!newPart.name.trim()) { setAddPartError('Part name is required.'); return }
    setAddPartSaving(true)
    setAddPartError('')
    try {
      const res = await apiClient.post('/catalogue/parts', {
        name: newPart.name.trim(),
        part_number: newPart.part_number.trim() || null,
        brand: newPart.brand.trim() || null,
        default_price: newPart.default_price ? Number(newPart.default_price) : 0,
        description: newPart.description.trim() || null,
        part_type: 'part',
      })
      const created = res.data.part || res.data
      const newItem: SearchItem = {
        id: created.id,
        name: created.name,
        sku: created.part_number || null,
        cost_price: Number(created.default_price) || 0,
        source: 'catalogue',
      }
      setSearchItems(prev => [...prev, newItem])
      selectItem(newItem)
      setShowAddPart(false)
    } catch (err: any) {
      setAddPartError(err?.response?.data?.detail || 'Failed to create part.')
    } finally { setAddPartSaving(false) }
  }

  const lineTotal = createLines.reduce((sum, l) => sum + l.quantity * l.unit_cost, 0)

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
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Branch</th>
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
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {po.branch_id ? ((branchList ?? []).find(b => b.id === po.branch_id)?.name ?? '—') : '—'}
                    </td>
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
          {/* Supplier live search */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Supplier *</label>
            {createSupplierId ? (
              <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2">
                <span className="flex-1 text-sm text-gray-900">{createSupplierName}</span>
                <button type="button" onClick={clearSupplier} className="rounded p-1 text-gray-400 hover:text-gray-600 text-xs" aria-label="Change supplier">✕</button>
              </div>
            ) : (
              <div ref={supplierRef} className="relative">
                <input
                  type="text"
                  value={supplierQuery}
                  onChange={e => { setSupplierQuery(e.target.value); setSupplierDropdownOpen(true) }}
                  onFocus={() => setSupplierDropdownOpen(true)}
                  placeholder="Search or type supplier name…"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  autoComplete="off"
                />
                {supplierDropdownOpen && (
                  <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
                    {filteredSuppliers.length > 0 && filteredSuppliers.slice(0, 10).map(s => (
                      <button key={s.id} type="button" onClick={() => selectSupplier(s)}
                        className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50">
                        <span className="font-medium text-gray-900">{s.name}</span>
                        {s.contact_name && <span className="ml-2 text-xs text-gray-500">{s.contact_name}</span>}
                      </button>
                    ))}
                    {filteredSuppliers.length === 0 && supplierQuery.length > 0 && (
                      <div className="px-3 py-2 text-sm text-gray-500">No suppliers match "{supplierQuery}"</div>
                    )}
                    {filteredSuppliers.length === 0 && supplierQuery.length === 0 && suppliers.length === 0 && (
                      <div className="px-3 py-2 text-sm text-gray-500">No suppliers yet</div>
                    )}
                    <button type="button" onClick={openAddSupplier}
                      className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm font-medium text-blue-600 hover:bg-blue-50">
                      + Add New Supplier{supplierQuery.trim() ? ` "${supplierQuery.trim()}"` : ''}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          <Input label="Expected Delivery" type="date" value={createExpectedDelivery}
            onChange={e => setCreateExpectedDelivery(e.target.value)} />

          {/* Line items */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Line Items</label>
            <div className="flex gap-2 mb-2 items-end">
              {/* Product/part live search */}
              <div className="flex-1">
                <label className="block text-xs font-medium text-gray-600 mb-1">Part / Product</label>
                {selectedItem ? (
                  <div className="flex items-center gap-2 rounded-md border border-gray-300 bg-gray-50 px-3 py-2 h-10">
                    <span className="flex-1 text-sm text-gray-900 truncate">{selectedItem.name}</span>
                    <button type="button" onClick={clearItem} className="text-gray-400 hover:text-gray-600 text-xs shrink-0">✕</button>
                  </div>
                ) : (
                  <div ref={productRef} className="relative">
                    <input
                      type="text"
                      value={productQuery}
                      onChange={e => { setProductQuery(e.target.value); setProductDropdownOpen(true) }}
                      onFocus={() => setProductDropdownOpen(true)}
                      placeholder="Search parts…"
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm h-10 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      autoComplete="off"
                    />
                    {productDropdownOpen && (
                      <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-48 overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
                        {filteredItems.slice(0, 10).map(item => (
                          <button key={item.id} type="button" onClick={() => selectItem(item)}
                            className="w-full px-3 py-2 text-left text-sm hover:bg-gray-50">
                            <div className="flex items-center justify-between">
                              <span className="font-medium text-gray-900">{item.name}</span>
                              <span className="text-xs text-gray-500 ml-2">{formatNZD(item.cost_price)}</span>
                            </div>
                            {item.sku && <div className="text-xs text-gray-400">{item.sku}</div>}
                          </button>
                        ))}
                        {filteredItems.length === 0 && productQuery.length > 0 && (
                          <div className="px-3 py-2 text-sm text-gray-500">No parts match "{productQuery}"</div>
                        )}
                        {filteredItems.length === 0 && productQuery.length === 0 && searchItems.length === 0 && (
                          <div className="px-3 py-2 text-sm text-gray-500">No parts in catalogue yet</div>
                        )}
                        <button type="button" onClick={openAddPart}
                          className="w-full border-t border-gray-100 px-3 py-2 text-left text-sm font-medium text-blue-600 hover:bg-blue-50">
                          + Add New Part{productQuery.trim() ? ` "${productQuery.trim()}"` : ''}
                        </button>
                      </div>
                    )}
                  </div>
                )}
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
                <Button size="sm" variant="secondary" onClick={addLine} disabled={!selectedItem || !addQty || !addCost}>Add</Button>
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

      {/* Add Supplier Modal */}
      <Modal open={showAddSupplier} onClose={() => setShowAddSupplier(false)} title="New Supplier">
        <div className="space-y-3">
          <Input label="Supplier name *" value={newSupplier.name}
            onChange={e => setNewSupplier(prev => ({ ...prev, name: e.target.value }))} />
          <Input label="Contact person" value={newSupplier.contact_name}
            onChange={e => setNewSupplier(prev => ({ ...prev, contact_name: e.target.value }))} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Email" type="email" value={newSupplier.email}
              onChange={e => setNewSupplier(prev => ({ ...prev, email: e.target.value }))} />
            <Input label="Phone" value={newSupplier.phone}
              onChange={e => setNewSupplier(prev => ({ ...prev, phone: e.target.value }))} />
          </div>
          <Input label="Address" value={newSupplier.address}
            onChange={e => setNewSupplier(prev => ({ ...prev, address: e.target.value }))} />
          {addSupplierError && <p className="text-sm text-red-600">{addSupplierError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowAddSupplier(false)}>Cancel</Button>
            <Button onClick={handleAddSupplier} loading={addSupplierSaving}>Create Supplier</Button>
          </div>
        </div>
      </Modal>

      {/* Add Part Modal */}
      <Modal open={showAddPart} onClose={() => setShowAddPart(false)} title="New Part">
        <div className="space-y-3">
          <Input label="Part name *" value={newPart.name}
            onChange={e => setNewPart(prev => ({ ...prev, name: e.target.value }))} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="Part number / SKU" value={newPart.part_number}
              onChange={e => setNewPart(prev => ({ ...prev, part_number: e.target.value }))} />
            <Input label="Brand" value={newPart.brand}
              onChange={e => setNewPart(prev => ({ ...prev, brand: e.target.value }))} />
          </div>
          <Input label="Default price (ex-GST)" type="number" min="0" step="0.01" value={newPart.default_price}
            onChange={e => setNewPart(prev => ({ ...prev, default_price: e.target.value }))} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea value={newPart.description} onChange={e => setNewPart(prev => ({ ...prev, description: e.target.value }))}
              rows={2} placeholder="Optional description…"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          {addPartError && <p className="text-sm text-red-600">{addPartError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowAddPart(false)}>Cancel</Button>
            <Button onClick={handleAddPart} loading={addPartSaving}>Create Part</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
